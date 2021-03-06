"""Collection of NASNet variants

The reference paper:

 - Learning Transferable Architectures for Scalable Image Recognition,
   arXiv 2017
 - Barret Zoph, Vijay Vasudevan, Jonathon Shlens, Quoc V. Le
 - https://arxiv.org/abs/1707.07012

The reference implementation:

1. TF Slim
 - https://github.com/tensorflow/models/blob/master/research/slim/nets/
   nasnet/nasnet.py
"""
from __future__ import absolute_import
from __future__ import division

import tensorflow as tf

from .layers import avg_pool2d
from .layers import batch_norm
from .layers import conv2d
from .layers import dropout
from .layers import fully_connected
from .layers import max_pool2d
from .layers import separable_conv2d
from .layers import convbn as conv
from .layers import sconvbn

from .ops import *
from .utils import set_args
from .utils import var_scope


def __args__(is_training):
    return [([avg_pool2d, max_pool2d], {'padding': 'SAME', 'scope': 'pool'}),
            ([batch_norm], {'decay': 0.9997, 'scale': True, 'epsilon': 0.001,
                            'is_training': is_training, 'fused': True,
                            'scope': 'bn'}),
            ([conv2d], {'padding': 'SAME', 'activation_fn': None,
                        'biases_initializer': None, 'scope': 'conv'}),
            ([dropout], {'is_training': is_training, 'scope': 'dropout'}),
            ([fully_connected], {'activation_fn': None, 'scope': 'fc'}),
            ([separable_conv2d], {'padding': 'SAME', 'activation_fn': None,
                                  'biases_initializer': None,
                                  'scope': 'sconv'})]


@var_scope('sconv')
def sconv(x, filters, kernel_size, stride=1, scope=None):
    x = relu(x)
    x = sconvbn(x, filters, kernel_size, stride=stride,
                depth_multiplier=1, scope='0')
    x = relu(x)
    x = sconvbn(x, filters, kernel_size,
                depth_multiplier=1, scope='1')
    return x


def nasnet(x, stem_filters, normals, filters, skip_reduction,
           use_aux, scaling, is_training, classes, scope=None, reuse=None):
    x = conv(x, stem_filters, 3, stride=2, padding='VALID', scope='conv0')

    x, p = reductionA(x, None, filters * scaling ** (-2), scope='stem1')
    x, p = reductionA(x, p, filters * scaling ** (-1), scope='stem2')

    for i in range(normals):
        x, p = normalA(x, p, filters, scope="normal%d" % (i + 1))

    x, p0 = reductionA(x, p, filters * scaling,
                       scope="reduction%d" % normals)
    p = p0 if not skip_reduction else p

    for i in range(normals):
        x, p = normalA(x, p, filters * scaling,
                       scope="normal%d" % (i + normals + 1))

    if use_aux is True:
        a = aux(x, classes, scope='aux')

    x, p0 = reductionA(x, p, filters * scaling ** 2,
                       scope="reduction%d" % (normals * 2))
    p = p0 if not skip_reduction else p

    for i in range(normals):
        x, p = normalA(x, p, filters * scaling ** 2,
                       scope="normal%d" % (i + normals * 2 + 1))

    x = relu(x, name='relu')
    x = reduce_mean(x, [1, 2], name='avgpool')
    x = dropout(x, keep_prob=0.5, scope='dropout')
    x = fully_connected(x, classes, scope='logits')
    x = softmax(x, name='probs')
    x.aliases = [tf.get_variable_scope().name]
    return x


@var_scope('nasnetAlarge')
@set_args(__args__)
def nasnetAlarge(x, is_training=False, classes=1000, scope=None, reuse=None):
    return nasnet(x, 96, 6, 168, True, True, 2,
                  is_training, classes, scope, reuse)


@var_scope('nasnetAmobile')
@set_args(__args__)
def nasnetAmobile(x, is_training=False, classes=1000, scope=None, reuse=None):
    return nasnet(x, 32, 4, 44, False, True, 2,
                  is_training, classes, scope, reuse)


@var_scope('adjust')
def adjust(p, x, filters, scope=None):
    if p is None:
        p = x
    elif int(p.shape[1]) != int(x.shape[1]):
        p = relu(p, name='relu')
        p1 = avg_pool2d(p, 1, stride=2, padding='VALID', scope='pool1')
        p1 = conv2d(p1, int(filters / 2), 1, scope='conv1')
        p2 = pad(p, [[0, 0], [0, 1], [0, 1], [0, 0]])[:, 1:, 1:, :]
        p2 = avg_pool2d(p2, 1, stride=2, padding='VALID', scope='pool2')
        p2 = conv2d(p2, int(filters / 2), 1, scope='conv2')
        p = concat([p1, p2], axis=3, name='concat')
        p = batch_norm(p, scope='bn')
    elif int(p.shape[-1]) != filters:
        p = relu(p, name='relu')
        p = conv(p, filters, 1, scope='prev_1x1')
    return p


@var_scope('normalA')
def normalA(x, p, filters, scope=None):
    """Normal cell for NASNet-A (Fig. 4 in the paper)"""
    p = adjust(p, x, filters)

    h = relu(x)
    h = conv(h, filters, 1, scope='1x1')

    x1 = add(sconv(h, filters, 3, scope='left1'), h, name='add1')
    x2 = add(sconv(p, filters, 3, scope='left2'),
             sconv(h, filters, 5, scope='right2'), name='add2')
    x3 = add(avg_pool2d(h, 3, stride=1, scope='left3'), p, name='add3')
    x4 = add(avg_pool2d(p, 3, stride=1, scope='left4'),
             avg_pool2d(p, 3, stride=1, scope='right4'), name='add4')
    x5 = add(sconv(p, filters, 5, scope='left5'),
             sconv(p, filters, 3, scope='right5'), name='add5')

    return concat([p, x2, x5, x3, x4, x1], axis=3, name='concat'), x


@var_scope('reductionA')
def reductionA(x, p, filters, scope=None):
    """Reduction cell for NASNet-A (Fig. 4 in the paper)"""
    p = adjust(p, x, filters)

    h = relu(x)
    h = conv(h, filters, 1, scope='1x1')

    x1 = add(sconv(p, filters, 7, stride=2, scope='left1'),
             sconv(h, filters, 5, stride=2, scope='right1'), name='add1')
    x2 = add(max_pool2d(h, 3, scope='left2'),
             sconv(p, filters, 7, stride=2, scope='right2'), name='add2')
    x3 = add(avg_pool2d(h, 3, scope='left3'),
             sconv(p, filters, 5, stride=2, scope='right3'), name='add3')
    x4 = add(max_pool2d(h, 3, scope='left4'),
             sconv(x1, filters, 3, scope='right4'), name='add4')
    x5 = add(avg_pool2d(x1, 3, stride=1, scope='left5'), x2, name='add5')

    return concat([x2, x3, x5, x4], axis=3, name='concat'), x


@var_scope('aux')
def aux(x, classes, scope=None):
    x = relu(x, name='relu1')
    x = avg_pool2d(x, 5, stride=3, padding='VALID', scope='pool')
    x = conv(x, 128, 1, scope='proj')
    x = relu(x, name='relu2')
    x = conv(x, 768, int(x.shape[1]), padding='VALID', scope='conv')
    x = relu(x, name='relu3')
    x = squeeze(x, [1, 2], name='squeeze')
    x = fully_connected(x, classes, scope='logits')
    x = softmax(x, name='probs')
    return x


# Simple alias.
NASNetAlarge = nasnetAlarge
NASNetAmobile = nasnetAmobile
