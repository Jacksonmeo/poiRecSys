"""One-command entry point for the standalone T10e-2 project."""

# run.py —— 统一入口脚本
# 本模块是整个 T10e-2 项目的命令行统一入口，将评估、训练、记忆构建和全流程流水线
# 集中到一个命令中执行。用户只需通过 command 参数选择流水线阶段，由 main() 函数
# 解析参数后调用 run_module() 启动对应的 Python 子模块。

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def run_module(module: str, *args: str) -> None:
    """以子进程方式运行指定的 Python 模块。

    通过 subprocess 调用当前 Python 解释器执行目标模块，统一设置
    UTF-8 编码环境变量，确保跨平台（特别是 Windows GBK 环境）输出
    不出现乱码。

    参数:
        module: 要运行的模块名（如 "src.t10e2"）。
        *args: 传递给模块的命令行参数。
    """
    command = [sys.executable, "-m", module, *args]
    print("\n$ " + " ".join(command), flush=True)
    env = os.environ.copy()
    # Windows often defaults redirected child output to GBK. Several original
    # experiment reports contain Unicode symbols, so force a portable UTF-8 CLI.
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def main() -> None:
    """命令行入口函数，解析用户指定的流水线阶段并分发到对应子模块。

    支持的 command:
        - smoke:            运行冒烟测试，快速验证环境是否可用。
        - evaluate:         使用固定（已发布）配置评估 T10e-2 模型。
        - evaluate-search:  执行穷举验证搜索，寻找最优超参数组合。
        - train:            单独训练 T9 模型。
        - memory:           构建转移记忆（Transition Memory），供因果融合使用。
        - full:             完整流水线（训练 + 记忆 + 固定配置评估）。
        - full-search:      完整流水线（训练 + 记忆 + 搜索评估）。

    可选参数 --epochs 和 --batch-size 控制 T9 训练阶段的超参数。
    """
    parser = argparse.ArgumentParser(description="Standalone T10e-2 full pipeline")
    parser.add_argument(
        "command",
        choices=("smoke", "evaluate", "evaluate-search", "train", "memory", "full", "full-search"),
        help="evaluate uses the published config; evaluate-search repeats the exhaustive validation search",
    )
    parser.add_argument("--epochs", type=int, default=50, help="T9 epochs for train/full")
    parser.add_argument("--batch-size", type=int, default=512, help="T9 training batch size")
    args = parser.parse_args()

    if args.command == "smoke":
        run_module("src.smoke_test")
    elif args.command == "evaluate":
        run_module("src.t10e2", "--fixed-config")
    elif args.command == "evaluate-search":
        run_module("src.t10e2")
    elif args.command == "train":
        run_module("src.train_t9", "--epochs", str(args.epochs), "--batch_size", str(args.batch_size))
    elif args.command == "memory":
        run_module("src.build_transition_memory", "--top_k", "100")
    elif args.command in ("full", "full-search"):
        run_module("src.train_t9", "--epochs", str(args.epochs), "--batch_size", str(args.batch_size))
        run_module("src.build_transition_memory", "--top_k", "100")
        if args.command == "full":
            run_module("src.t10e2", "--fixed-config")
        else:
            run_module("src.t10e2")


if __name__ == "__main__":
    main()
