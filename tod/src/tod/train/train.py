"""
@author: Mathieu Tuli
@github: MathieuTuli
@email: tuli.mathieu@gmail.com
"""
from typing import Union, Dict, Any, List
from pathlib import Path

import time

from transformers import PreTrainedModel as HFPretrained
from configargparse import Namespace

import torch

from .models import get_tokenizer, get_model
from .optim import get_optimizer_scheduler
from .data.utils import load_data
from .io import create_dir


class TrainingAgent:
    config: Dict[str, Any] = None
    train_loader = None
    val_loader = None
    model: torch.nn.Module = None
    optimizer: torch.optim.Optimizer = None
    scheduler = None
    loss = None
    output_filename: Path = None
    checkpoint = None
    device = 'cuda'

    def __init__(self, args: Namespace,) -> None:
        self.args = args
        self.reset()

    def reset(self) -> None:
        self.tokenizer = get_tokenizer(self.tokenizer)
        self.train_loader = load_data(src_fname=self.args.data.train_src,
                                      tgt_fname=self.args.data.train_tgt,
                                      tokenizer=self.tokenizer,
                                      max_length=self.args.train.max_length,
                                      batch_size=self.args.train.batch_size,
                                      num_workers=self.args.train.num_workers)
        self.val_loader = load_data(src_fname=self.args.data.val_src,
                                    tgt_fname=self.args.data.val_tgt,
                                    tokenizer=get_tokenizer(self.tokenizer),
                                    max_length=self.args.train.max_length,
                                    batch_size=self.args.train.batch_size,
                                    num_workers=self.args.train.num_workers)
        self.model = get_model(self.args.model)
        self.model.to(self.device)
        if len(self.args.train.gpu) > 1:
            self.model = torch.nn.DataParallel(self.model)
        self.optimizer, self.scheduler = get_optimizer_scheduler(
            optim_method=self.args.train.optimizer,
            scheduler_method=self.args.train.scheduler,
            net_parameters=self.model.parameters(),
            max_epochs=self.args.train.max_epochs,
            train_loader_len=len(self.train_loader),
            optimizer_kwargs=self.args.train.optimizer_kwargs,
            scheduler_kwargs=self.args.train.scheduler_kwargs)

        self.loss = self.get_loss(self.args.train.loss)
        self.output_dir = create_dir(self.args.io.output)
        self.checkpoint_dir = create_dir(self.args.io.checkpoint)
        self.task_setup()

    def task_setup(self) -> None:
        if self.args.data.name == 'MultiWOZ':
            if self.args.data.task == 'causal':
                self.tokenizer.add_special_tokens(
                    {'bos_token': '<|endoftext|>'})
                self.tokenizer.add_special_tokens(
                    {'eos_token': '<|endoftext|>'})

    def train(self) -> None:
        for trial in range(self.args['num_trials']):
            self.reset()
            self.run_epochs(trial, range(0, self.config['max_epochs']))

    def run_epochs(self, trial: int, epochs: List[int]) -> None:
        # total_steps = len(self.train_loader) * self.config['max_epochs']
        for epoch in epochs:
            start_time = time.time()
            train_loss = self.epoch_iteration(trial, epoch)
            epoch_time = time.time()
            val_loss = self.evaluate(epoch)
            end_time = time.time()
            print(f"E time: {epoch_time - start_time} | "
                  f"T time {end_time - epoch_time} | " +
                  f"Train Loss {train_loss} | " +
                  f"Val Loss {val_loss}")

    def epoch_iteration(self, trial: int, epoch: int) -> float:
        self.model.train()
        train_loss = 0
        for step, (inputs, mask, targets) in enumerate(self.train_loader):
            if self.args.train.gpu is not None and self.device == 'cuda':
                inputs = inputs.cuda(self.train.gpu, non_blocking=True)
                input_mask = mask.cuda(self.train.gpu, non_blocking=True)
                targets = targets.cuda(self.train.gpu, non_blocking=True)
            self.optimizer.zero_grad()
            loss, outputs = self.model(
                inputs, attention_mask=input_mask, targets=targets)
            # loss = self.criterion(outputs, targets)
            if len(self.args.train.gpu) > 1:
                loss = loss.mean()
            # if self.args.train.gradient_accumulation_steps > 1:
            # loss /= self.args.train.gradient_accumulation_steps
            train_loss += loss.item()
            loss.backward()
            if self.args.train.clip_grad > 0:
                torch.nn.utils.clip_grad_norm(self.model.parameters(),
                                              self.args.train.clip_grad)
            self.optimizer.step()
            if self.scheduler is not None:
                self.scheduler.step()
        return train_loss

    def validate(self, epoch: int) -> float:
        self.model.eval()
        val_loss = 0
        for inputs, mask, targets in self.val_loader:
            if self.gpu is not None and self.device == 'cuda':
                inputs = inputs.cuda(self.gpu, non_blocking=True)
                input_mask = mask.cuda(self.gpu, non_blocking=True)
                targets = targets.cuda(self.gpu, non_blocking=True)
            with torch.no_grad():
                loss, outputs = self.model(
                    inputs, attention_mask=input_mask, targets=targets)
            if len(self.args.train.gpu) > 1:
                loss = loss.mean()
            val_loss += loss.item()
        return val_loss


def main(args: Namespace) -> None:
    training_agent = TrainingAgent(args=args)
    training_agent.train()
