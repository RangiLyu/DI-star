"""
Copyright 2020 Sensetime X-lab. All Rights Reserved

Main Function:
    1. Levenshtein_distance and hamming_distance: Calculate the levenshtein distance and the hamming distance
        of the given inputs.
"""

import random

import torch


def levenshtein_distance(pred, target, pred_extra=None, target_extra=None, extra_fn=None):
    r"""
    Overview:
        Levenshtein Distance(Edit Distance)

    Arguments:
        Note:
            N1 >= 0, N2 >= 0

        - pred (:obj:`torch.LongTensor`): shape[N1]
        - target (:obj:`torch.LongTensor`): shape[N2]
        - pred_extra (:obj:`torch.Tensor or None`)
        - target_extra (:obj:`torch.Tensor or None`)
        - extra_fn (:obj:`function or None`): if specified, the distance metric of the extra input data

    Returns:
        - (:obj:`torch.FloatTensor`) distance(scalar), shape[1]

    Test:
        torch_utils/network/tests/test_metric.py
    """
    assert (isinstance(pred, torch.Tensor) and isinstance(target, torch.Tensor))
    assert (pred.dtype == torch.long and target.dtype == torch.long), '{}\t{}'.format(pred.dtype, target.dtype)
    assert (pred.device == target.device)
    assert (type(pred_extra) == type(target_extra))
    if not extra_fn:
        assert (not pred_extra)
    N1, N2 = pred.shape[0], target.shape[0]
    assert (N1 >= 0 and N2 >= 0)
    if N1 == 0 or N2 == 0:
        distance = max(N1, N2)
    else:
        dp_array = torch.zeros(N1 + 1, N2 + 1).float()
        dp_array[0, :] = torch.arange(0, N2 + 1)
        dp_array[:, 0] = torch.arange(0, N1 + 1)
        for i in range(1, N1 + 1):
            for j in range(1, N2 + 1):
                if pred[i-1] == target[j-1]:
                    if extra_fn:
                        dp_array[i, j] = dp_array[i - 1, j - 1] + extra_fn(pred_extra[i-1], target_extra[j-1])
                    else:
                        dp_array[i, j] = dp_array[i - 1, j - 1]
                else:
                    dp_array[i, j] = min(dp_array[i - 1, j] + 1, dp_array[i, j - 1] + 1, dp_array[i - 1, j - 1] + 1)
        distance = dp_array[N1, N2]
    return torch.FloatTensor([distance]).to(pred.device)


def hamming_distance(pred, target, weight=1.):
    r'''
    Overview:
        Hamming Distance

    Arguments:
        Note:
            pred, target are also boolean vector(0 or 1)

        - pred (:obj:`torch.LongTensor`): pred input, shape[B, N], while B is the batch size
        - target (:obj:`torch.LongTensor`): target input, shape[B, N], while B is the batch size

    Returns:
        - distance(:obj:`torch.LongTensor`): distance(scalar), the shape[1]

    Shapes:
        - pred & target (:obj:`torch.LongTensor`): shape :math:`(B, N)`, \
            while B is the batch size and N is the dimension

    Test:
        torch_utils/network/tests/test_metric.py
    '''
    assert (isinstance(pred, torch.Tensor) and isinstance(target, torch.Tensor))
    assert (pred.dtype == torch.long and target.dtype == torch.long)
    assert (pred.device == target.device)
    assert (pred.shape == target.shape)
    return pred.ne(target).sum(dim=1).float().mul_(weight)
