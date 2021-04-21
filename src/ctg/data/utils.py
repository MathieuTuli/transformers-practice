"""
@author: Mathieu Tuli
@github: MathieuTuli
@email: tuli.mathieu@gmail.com
"""
from typing import List, Union, Dict, Tuple
from pathlib import PosixPath

import numpy as np
import spacy
import torch
import json

from transformers.tokenization_utils_base import PreTrainedTokenizerBase
# from transformers import LineByLineTextDataset
from transformers import DataCollatorForSeq2Seq, default_data_collator
from torch.utils.data import Dataset, DataLoader, \
    RandomSampler, SequentialSampler
from torch.nn.utils.rnn import pad_sequence
from datasets import load_dataset

from ..utils.logging import logger


def right_shift(start_token_id: int,
                pad_token_id: int,
                input_ids: torch.Tensor) -> torch.Tensor:
    # shift inputs to the right
    shifted_input_ids = input_ids.new_zeros(input_ids.shape)
    shifted_input_ids[..., 1:] = input_ids[..., :-1].clone()
    shifted_input_ids[..., 0] = start_token_id

    assert pad_token_id is not None, \
        "self.model.config.pad_token_id has to be defined."
    # replace possible -100 values in labels by `pad_token_id`
    shifted_input_ids.masked_fill_(shifted_input_ids == -100, pad_token_id)

    assert torch.all(shifted_input_ids >= 0).item(
    ), "Verify that `shifted_input_ids` has only positive values"

    return shifted_input_ids


class LineByLineTextDataset(Dataset):
    def __init__(self, tokenizer, file_path, max_length=512):
        with open(file_path, encoding="utf-8") as f:
            lines = [line for line in f.read().splitlines() if (
                len(line) > 0 and not line.isspace())]

        tokenized = tokenizer.batch_encode_plus(
            lines,
            add_special_tokens=True,
            padding=True,
            # return_tensors='pt',
            return_attention_mask=True,
            truncation=True,
            max_length=max_length)
        self.examples = tokenized['input_ids']
        self.masks = tokenized['attention_mask']

    def __len__(self):
        return len(self.examples)

    def __getitem__(self, i):
        # return (torch.LongTensor(self.examples['input_ids'][i]),
        #         torch.LongTensor(self.examples['attention_mask'][i]))
        # return torch.LongTensor(self.examples[i])
        return (torch.LongTensor(self.examples[i]),
                torch.LongTensor(self.masks[i]))


def extend_vocabulary(tokenizer, fname: PosixPath) -> None:
    if fname.suffix not in set(['.txt']) or not fname.exists():
        raise ValueError(f"Unknown src file {fname}. Files must be",
                         " .txt line by line files")
    vocab = [line.strip() for line in fname.open('r').readlines()]
    tokenizer.add_tokens(vocab)


def load_seq2seq_data(
        fname: PosixPath,
        tokenizer: PreTrainedTokenizerBase,
        # model: torch.nn.Module,
        max_src_length: int,
        max_tgt_length: int,
        pad_to_max_length: bool,
        batch_size: int,
        cache_dir: PosixPath,
        max_samples: int = -1,
        overwrite_cache: bool = False,
        num_workers: int = 4,
        ignore_pad_for_loss: bool = True,
        split: str = 'train',
        prefix: str = '',
        distributed: bool = False) -> None:
    if fname.suffix not in set(['.json']) or not fname.exists():
        raise ValueError(f"Unknown src file {fname}. Files must be",
                         " .json files")
    dataset = load_dataset('json',
                           data_files={split: str(fname)},
                           field='data',
                           cache_dir=cache_dir,
                           split=split)
    # dataset = LineByLineTextDataset(tokenizer, file_path=str(fname),
    #                                 max_length=max_length)

    logger.info("Loading data")

    def preprocess(examples: List[str]) -> Tuple[List[int], None]:
        inputs = examples["source"]
        inputs = [prefix + i for i in inputs]
        inputs = tokenizer(
            inputs,
            # add_special_tokens=True,
            padding='max_length' if pad_to_max_length else False,
            max_length=max_src_length,
            return_tensors='np',
            truncation=True)
        targets = examples["target"]
        with tokenizer.as_target_tokenizer():
            targets = tokenizer(
                targets,
                # add_special_tokens=True,
                padding='max_length' if pad_to_max_length else False,
                max_length=max_tgt_length,
                return_tensors='np',
                truncation=True)
            # -100 is a specific number for masking
            if pad_to_max_length and ignore_pad_for_loss:
                targets["input_ids"] = [
                    [(_label if _label != tokenizer.pad_token_id else -100)
                        for _label in label] for label in targets["input_ids"]]
        # del inputs['attention_mask']
        inputs["labels"] = targets["input_ids"]
        return inputs

    if max_samples > 0:
        dataset = dataset.select(range(min(max_samples, len(dataset))))
    dataset = dataset.map(
        preprocess,
        batched=True,
        remove_columns=dataset.column_names,
        num_proc=num_workers,
        # batch_size=batch_size,
        load_from_cache_file=not overwrite_cache
    )
    # dataset.set_format(type='torch')
    # if not distributed:
    #     sampler = RandomSampler(dataset) if split == 'train'\
    #         else SequentialSampler(dataset)
    # else:
    #     sampler = torch.utils.data.distributed.DistributedSampler(
    #         dataset, shuffle=split == 'train')
    # if task == 'nmt':
    #     data_collator = DataCollatorForSeq2Seq(
    #         tokenizer,
    #         model=model,
    #         label_pad_token_id=-100)
    if pad_to_max_length:
        collator = default_data_collator
    else:
        collator = DataCollatorForSeq2Seq(
            tokenizer,
            model=model,
            label_pad_token_id=-100 if ignore_pad_for_loss else
            tokenizer.pad_token_id,)
    return dataset


def read_lines(filename: Union[str, PosixPath]) -> List[str]:
    """Read file and split into lines"""
    lines = open(filename).read().strip().split('\n')
    return [line for line in lines if (len(line) > 0 and not line.isspace())]


def vocabulary_indices(vocabulary: List[str]) -> Dict[str, int]:
    return {word: i for i, word in enumerate(sorted(list(vocabulary)))}
