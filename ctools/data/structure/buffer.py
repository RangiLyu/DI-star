import copy
import time
import numbers
import os
import pprint
from queue import Queue
import random
from typing import Union, NoReturn, Any
from collections import defaultdict

import numpy as np

from ctools.data.structure.segment_tree import SumSegmentTree, MinSegmentTree
import threading
from ctools.utils import remove_file


class PrioritizedBuffer:
    r"""
    Overview:
        prioritized buffer, store and sample data
    Interface:
        __init__, append, extend, sample, update
    Property:
        maxlen, validlen, beta
    Note:
        this buffer doesn't refer to multi-thread/multi-process, thread-safe should be ensured by the caller
    """

    def __init__(
        self,
        maxlen: int,
        max_reuse: Union[int, None] = None,
        min_sample_ratio: float = 1.,
        alpha: float = 0.,
        beta: float = 0.,
        enable_track_used_data: bool = False,
        delete_cache_length=50,
        path_traj=None,
    ):
        r"""
        Overview:
            initialize the buffer
        Arguments:
            - maxlen (:obj:`int`): the maximum value of the buffer length
            - max_reuse (:obj:`int` or None): the maximum reuse times of each element in buffer
            - min_sample_ratio (:obj:`float`): the minimum ratio of the current element size in buffer
                                                divides sample size
            - alpha (:obj:`float`): how much prioritization is used(0: no prioritization, 1: full prioritization)
            - beta (:obj:`float`): how much correction is used(0: no correction, 1: full correction)
            - enable_track_used_data (:obj:`bool`): whether tracking the used data
        """
        # TODO(nyz) remove elements according to priority
        # TODO(nyz) add statistics module
        self._maxlen = maxlen
        self._enable_track_used_data = enable_track_used_data
        if self._enable_track_used_data:
            self.used_data = defaultdict(list)
            self._path_traj = path_traj

        self._data = [None for _ in range(maxlen)]
        self._reuse_count = {idx: 0 for idx in range(maxlen)}

        self.max_reuse = max_reuse if max_reuse is not None else np.inf
        assert (min_sample_ratio >= 1)
        self.min_sample_ratio = min_sample_ratio
        assert (0 <= alpha <= 1)
        self.alpha = alpha
        assert (0 <= beta <= 1)
        self._beta = beta
        # capacity needs to be the power of 2
        capacity = int(np.power(2, np.ceil(np.log2(self.maxlen))))
        self.sum_tree = SumSegmentTree(capacity)
        self.min_tree = MinSegmentTree(capacity)

        self.max_priority = 1.0
        # current valid data count
        self._valid_count = 0
        self._push_count = 0
        self.pointer = 0
        # generate the unique id for each data
        self.latest_data_id = 0

        # data check function list
        self.check_list = [lambda x: isinstance(x, dict)]


    def _set_weight(self, idx: int, data):
        r"""
        Overview:
            set the priority and tree weight of the input data
        Arguments:
            - idx (:obj:`int`) the index which the data will be inserted into
            - data (:obj:`T`) the data which will be inserted
        """
        if 'priority' not in data.keys() or data['priority'] is None:
            data['priority'] = self.max_priority
        # weight = priority ** alpha
        weight = data['priority'] ** self.alpha
        self.sum_tree[idx] = weight
        self.min_tree[idx] = weight

    def sample(self, size: int, recycle_paths) -> Union[None, list]:
        r"""
        Overview:
            sample data with `size`
        Arguments:
            - size (:obj:`int`): the number of the data will be sampled
        Returns:
            - sample_data (:obj:`list`): if check fails return None, otherwise, returns a list with length `size`,
                                         and each data owns keys: original data keys +
                                         ['IS', 'priority', 'replay_unique_id', 'replay_buffer_idx']
        """
        if self._enable_track_used_data:
            for path in recycle_paths:
                if path in self.used_data.keys():
                    self.used_data[path].append(1)
                    if len(self.used_data[path]) >= (self.max_reuse + 1) * 2 and sum(self.used_data[path]) == 0:
                        self.used_data.pop(path)
                        file_path = os.path.join(self._path_traj, path)
                        if os.path.exists(file_path):
                            remove_file(file_path)
        if not self._sample_check(size):
            return None
        indices = self._get_indices(size)
        return self._sample_with_indices(indices)

    def append(self, ori_data):
        r"""
        Overview:
            append a data item into queue
        Arguments:
            - ori_data (:obj:`T`): the data which will be inserted
        """
        data = copy.deepcopy(ori_data)
        try:
            assert (self._data_check(data))
        except AssertionError:
            # if data check fails, just return without any operations
            print('illegal data {}, reject it...'.format(type(data)))
            return
        if self._data[self.pointer] is None:
            self._valid_count += 1
        else:
            if self._enable_track_used_data:
                if sum(self.used_data[self._data[self.pointer]['traj_id']]) == 0:
                    self.used_data.pop(self._data[self.pointer]['traj_id'])
                    file_path = os.path.join(self._path_traj, self._data[self.pointer]['traj_id'])
                    if os.path.exists(file_path):
                        os.remove(file_path)
                else:
                    for i in range(self.max_reuse + 1 - self._reuse_count[self.pointer]):
                        self.used_data[self._data[self.pointer]['traj_id']] += [-1, 1]

        self._push_count += 1
        data['replay_unique_id'] = self.latest_data_id
        data['replay_buffer_idx'] = self.pointer
        self._set_weight(self.pointer, data)
        self._data[self.pointer] = data
        self._reuse_count[self.pointer] = 0
        self.pointer = (self.pointer + 1) % self._maxlen
        self.latest_data_id += 1

    def extend(self, ori_data):
        r"""
        Overview:
            extend a data list into queue
        Arguments:
            - ori_data (:obj:`T`): the data list
        """
        data = copy.deepcopy(ori_data)
        check_result = [self._data_check(d) for d in data]
        # only keep the data pass the check
        valid_data = [d for d, flag in zip(data, check_result) if flag]
        length = len(valid_data)
        for i in range(length):
            valid_data[i]['replay_unique_id'] = self.latest_data_id + i
            valid_data[i]['replay_buffer_idx'] = (self.pointer + i) % self.maxlen
            self._set_weight((self.pointer + i) % self.maxlen, valid_data[i])
            if self._data[(self.pointer + i) % self.maxlen] is None:
                self._valid_count += 1
            self._push_count += 1

        # the two case of the relationship among pointer, data length and queue length
        if self.pointer + length <= self._maxlen:
            self._data[self.pointer:self.pointer + length] = valid_data
            for idx in range(self.pointer, self.pointer + length):
                self._reuse_count[idx] = 0
        else:
            mid = self._maxlen - self.pointer
            self._data[self.pointer:self.pointer + mid] = valid_data[:mid]
            self._data[:length - mid] = valid_data[mid:]
            assert self.pointer + mid == self._maxlen
            for idx in range(self.pointer, self.pointer + mid):
                self._reuse_count[idx] = 0
            for idx in range(length - mid):
                self._reuse_count[idx] = 0

        self.pointer = (self.pointer + length) % self._maxlen
        self.latest_data_id += length

    def update(self, info: dict):
        r"""
        Overview:
            update priority according to the id and idx
        Arguments:
            - info (:obj:`dict`): info dict contains all the necessary for update priority
        """
        data = [info['replay_unique_id'], info['replay_buffer_idx'], info['priority']]
        for id_, idx, priority in zip(*data):
            # if the data still exists in the queue, then do the update operation
            if self._data[idx] is not None \
                    and self._data[idx]['replay_unique_id'] == id_:  # confirm the same transition(data)
                assert priority > 0
                self._data[idx]['priority'] = priority
                self._set_weight(idx, self._data[idx])
                # update max priority
                self.max_priority = max(self.max_priority, priority)

    def _data_check(self, d) -> bool:
        r"""
        Overview:
            data legality check
        Arguments:
            - d (:obj:`T`): the data need to be checked
        Returns:
            - result (:obj:`bool`): whether the data pass the check
        """
        # only the data pass all the check function does the check return True
        return all([fn(d) for fn in self.check_list])

    def _get_indices(self, size: int) -> list:
        r"""
        Overview:
            according to the priority probability, get the sample index
        Arguments:
            - size (:obj:`int`): the number of the data will be sampled
        Returns:
            - index_list (:obj:`list`): a list including all the sample index
        """
        # average divide size intervals and sample from them
        intervals = np.array([i * 1.0 / size for i in range(size)])
        # uniform sample in each interval
        mass = intervals + np.random.uniform(size=(size, )) * 1. / size
        # rescale to [0, S), which S is the sum of the total sum_tree
        mass *= self.sum_tree.reduce()
        # find prefix sum index to approximate sample with probability
        return [self.sum_tree.find_prefixsum_idx(m) for m in mass]

    def _sample_check(self, size: int) -> bool:
        r"""
        Overview:
            check whether the buffer satisfies the sample condition
        Arguments:
            - size (:obj:`int`): the number of the data will be sampled
        Returns:
            - result (:obj:`bool`): whether the buffer can sample
        """
        if self._valid_count < size:
            print(
                "[INFO({})] no enough element for sample(expect: {}/current have: {})".format(
                    time.time(), size, self._valid_count
                )
            )
            return False
        elif self._push_count < self.min_sample_ratio:
            print(
                "[INFO({})] push count is not enough for sample(expect: {}/current have: {})".format(
                    time.time(), self.min_sample_ratio, self._push_count
                )
            )
        else:
            if random.randint(1, 10) == 1:
                print("[INFO({}) current data size:{}]".format(time.time(), self._valid_count))
            return True

    def _sample_with_indices(self, indices: list) -> list:
        r"""
        Overview:
            sample the data with indices and update the internal variable
        Arguments:
            - indices (:obj:`list`): a list including all the sample index
        Returns:
            - data (:obj:`list`) sampled data
        """
        # calculate max weight for normalizing IS
        sum_tree_root = self.sum_tree.reduce()
        p_min = self.min_tree.reduce() / sum_tree_root
        max_weight = (self._valid_count * p_min) ** (-self._beta)
        data = []
        for idx in indices:
            # deepcopy data for avoiding interference
            copy_data = copy.deepcopy(self._data[idx])
            assert (copy_data is not None)
            # get IS(importance sampling weight for gradient step)
            p_sample = self.sum_tree[copy_data['replay_buffer_idx']] / sum_tree_root
            weight = (self._valid_count * p_sample) ** (-self._beta)
            copy_data['IS'] = weight / max_weight
            self._reuse_count[idx] += 1
            # remove the item which reuse is bigger than max_reuse
            data.append(copy_data)
            if self._enable_track_used_data:
                self.used_data[copy_data['traj_id']].append(-1)
        for idx in indices:
            if self._reuse_count[idx] > self.max_reuse:
                self._data[idx] = None
                self.sum_tree[idx] = self.sum_tree.neutral_element
                self.min_tree[idx] = self.min_tree.neutral_element
                self._valid_count -= 1
        return data

    @property
    def maxlen(self) -> int:
        return self._maxlen

    @property
    def validlen(self) -> int:
        return self._valid_count

    @property
    def beta(self) -> float:
        return self._beta

    @beta.setter
    def beta(self, beta: float) -> NoReturn:
        self._beta = beta

    @property
    def push_count(self) -> int:
        return self._push_count