# -*- coding: utf-8 -*-
"""订单打包 profile 集合。"""
from . import menz, ward

MENZ = menz.profile
WARD = ward.profile
ALL = (MENZ, WARD)

__all__ = ["menz", "ward", "MENZ", "WARD", "ALL"]
