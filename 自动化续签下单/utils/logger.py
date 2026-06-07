"""
日志工具 - 统一配置 console 和 file 日志输出
"""

import logging
from pathlib import Path
from datetime import datetime


def setup_logger(name: str, log_dir: str = "logs", level=logging.INFO) -> logging.Logger:
    """
    配置并返回日志对象
    
    Args:
        name: 日志名称（通常为模块名）
        log_dir: 日志目录
        level: 日志等级
        
    Returns:
        logging.Logger: 配置好的日志对象
    """
    # 创建日志目录
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    
    # 创建日志对象
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # 避免重复添加处理器
    if logger.handlers:
        return logger
    
    # 日志格式
    log_format = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console 处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(log_format)
    logger.addHandler(console_handler)
    
    # File 处理器
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_path / f"renewal_order_{timestamp}.log"
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(level)
    file_handler.setFormatter(log_format)
    logger.addHandler(file_handler)
    
    return logger
