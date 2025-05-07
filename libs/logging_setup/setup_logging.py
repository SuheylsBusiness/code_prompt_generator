# setup_logging.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

import logging, os, portalocker, threading, colorlog, inspect
from datetime import datetime
from logging.handlers import BaseRotatingHandler

SUCCESS_LEVEL_NUM = 25
logging.addLevelName(SUCCESS_LEVEL_NUM, "SUCCESS")
def success(msg, *args, stacklevel=1, **kwargs): logging.log(SUCCESS_LEVEL_NUM, msg, *args, stacklevel=stacklevel+1, **kwargs)
if not hasattr(logging.Logger, 'success'): logging.Logger.success = lambda self, msg, *args, stacklevel=1, **kwargs: self.log(SUCCESS_LEVEL_NUM, msg, *args, stacklevel=stacklevel+1, **kwargs)
if not hasattr(logging, 'success'): logging.success = success

class EnhancedLogger(logging.Logger):
    def success(self, msg, *args, **kwargs): self.log(SUCCESS_LEVEL_NUM, msg, *args, **kwargs)
    def _log(self, level, msg, args, exc_info=None, extra=None, stack_info=False, stacklevel=1, **kwargs):
        super()._log(level, msg, args, exc_info, extra, stack_info, stacklevel)
logging.setLoggerClass(EnhancedLogger)
logging.getLogger("httpx").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.CRITICAL)
logging.getLogger("openai").setLevel(logging.CRITICAL)
logging.getLogger("requests").setLevel(logging.CRITICAL)

class ExcludeFilter(logging.Filter):
    def __init__(self, excluded_files=None):
        super().__init__()
        self.excluded_files = set(excluded_files or [])
    def filter(self, record): return os.path.basename(record.pathname) not in self.excluded_files

class KeywordTruncationFilter(logging.Filter):
    def __init__(self, truncate_keys=None):
        super().__init__()
        self.truncate_keys = [k.lower() for k in (truncate_keys or [])]
    def filter(self, record):
        original = record.getMessage()
        lower_msg = original.lower()
        for k in self.truncate_keys:
            pos = lower_msg.find(k)
            if pos != -1:
                record.msg = original[:pos].rstrip() + "..."
                record.args = ()
                break
        return True

# New Filter
# ------------------------------
class KeywordExcludeFilter(logging.Filter):
    def __init__(self, keywords=None):
        super().__init__()
        self.keywords = keywords or []
    def filter(self, record):
        msg = record.getMessage()
        for kw in self.keywords:
            if kw in msg: return False
        return True

class HierarchicalFormatter(logging.Formatter):
    def format(self, record):
        if not hasattr(record, 'func_hierarchy'):
            stack = [f for f in inspect.stack()[1:] if os.path.abspath(f.filename).startswith(os.getcwd()) and f.function != '<module>' and os.path.basename(f.filename) != 'setup_logging.py']
            record.func_hierarchy = self._condense_stack(stack) if stack else f"{os.path.basename(record.pathname)}:{record.funcName}"
        return super().format(record)
    def _condense_stack(self, call_stack):
        accum=[]; current_file=None; funcs=[]
        for frame in reversed(call_stack):
            fn,func=os.path.basename(frame.filename),frame.function
            if fn!=current_file:
                if current_file: accum.append(f"{current_file}:{' > '.join(funcs)}")
                current_file, funcs = fn,[func]
            else: funcs.append(func)
        if current_file: accum.append(f"{current_file}:{' > '.join(funcs)}")
        return ' > '.join(accum)

class DailyFileHandler(BaseRotatingHandler):
    def __init__(self, log_dir, log_prefix='app', encoding=None, delay=False):
        self.log_dir = os.path.abspath(log_dir)
        os.makedirs(self.log_dir, exist_ok=True)
        self.log_prefix = log_prefix
        super().__init__(self._compute_filename(), 'a', encoding, delay)
        self._emit_lock = threading.RLock()
        self.current_date_str = datetime.now().strftime('%Y-%m-%d')
    def _compute_filename(self):
        d = datetime.now()
        year_month = d.strftime('%Y-%m')
        week_label = "week" + d.strftime('%W')
        path = os.path.join(self.log_dir, year_month, week_label)
        os.makedirs(path, exist_ok=True)
        return os.path.join(path, f"{self.log_prefix}.{d.strftime('%Y-%m-%d')}.log")
    def shouldRollover(self, record): return datetime.now().strftime('%Y-%m-%d') != self.current_date_str
    def doRollover(self):
        if self.stream: self.stream.close(); self.stream = None
        self.current_date_str = datetime.now().strftime('%Y-%m-%d')
        self.baseFilename = self._compute_filename()
    def _open(self):
        stream = super()._open()
        try: import msvcrt, ctypes; handle = msvcrt.get_osfhandle(stream.fileno()); ctypes.windll.kernel32.SetHandleInformation(handle, 1, 0)
        except: pass
        return stream
    def emit(self, record):
        with self._emit_lock:
            if self.shouldRollover(record): self.doRollover()
            if self.stream is None: self.stream = self._open()
            portalocker.lock(self.stream, portalocker.LOCK_EX)
            try: super().emit(record)
            finally: portalocker.unlock(self.stream)

def setup_logging(log_path='logs', daily_rotation=True, log_level=logging.INFO, excluded_files=None, truncate_keys=None, exclude_keywords=None):
    logging.setLoggerClass(EnhancedLogger)
    logger = logging.getLogger()
    for h in list(logger.handlers): logger.removeHandler(h)
    logger.setLevel(log_level)
    if daily_rotation: file_handler = DailyFileHandler(log_dir=log_path, log_prefix='app', encoding='utf-8', delay=True)
    else:
        os.makedirs(log_path, exist_ok=True)
        file_handler = logging.FileHandler(os.path.join(log_path, 'app.log'), encoding='utf-8', delay=True)
    file_handler.setLevel(log_level)
    if excluded_files: file_handler.addFilter(ExcludeFilter(excluded_files))
    if truncate_keys: file_handler.addFilter(KeywordTruncationFilter(truncate_keys))
    if exclude_keywords: file_handler.addFilter(KeywordExcludeFilter(exclude_keywords))
    file_handler.setFormatter(HierarchicalFormatter('%(asctime)s - %(func_hierarchy)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    if excluded_files: console_handler.addFilter(ExcludeFilter(excluded_files))
    if truncate_keys: console_handler.addFilter(KeywordTruncationFilter(truncate_keys))
    if exclude_keywords: console_handler.addFilter(KeywordExcludeFilter(exclude_keywords))
    console_handler.setFormatter(colorlog.ColoredFormatter('%(log_color)s%(asctime)s - %(func_hierarchy)s - %(levelname)s - %(message)s', log_colors={'DEBUG':'white','INFO':'reset','SUCCESS':'green','WARNING':'yellow','ERROR':'red','CRITICAL':'bold_red'}))
    logger.addHandler(console_handler)
    logger.success("Logging initialized.")
    return logger
