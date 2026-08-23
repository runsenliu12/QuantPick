"""执行层公共工具：平台代码格式归一、模板元信息。

QuantPick 内部代码格式为 AKShare 风格（如 600000.SH / 510300.SH）。
不同券商/平台对代码格式要求不同，生成策略文件时统一转换。
"""
from __future__ import annotations


def norm_code(code: str, platform: str) -> str:
    """把内部代码转成目标平台需要的格式。

    - ptrade:  保持 600000.SH / 510300.SH（恒生用交易所后缀）
    - qmt:     纯数字 600000（迅投 xtquant 用数字代码）
    - joinquant: 600000.XSHG / 510300.XSHG（聚宽用 XSHG/XSHE）
    """
    code = str(code)
    if platform == "qmt":
        return code.split(".")[0]
    if platform == "joinquant":
        if code.endswith(".SH"):
            return code[:-3] + ".XSHG"
        if code.endswith(".SZ"):
            return code[:-3] + ".XSHE"
        return code
    return code  # ptrade 保持原样


META_LINE = "来源: {source} | 市场状态: {regime} | 仓位缩放: {scale}"
