from . import log
import argparse
from pathlib import Path
import shutil

TEMPL_DIR_NAME = 'example-chat-task'
TEMPL_DIR_PATH: Path = Path(__file__).parent / TEMPL_DIR_NAME

assert TEMPL_DIR_PATH.exists() and TEMPL_DIR_PATH.is_dir(), f'{TEMPL_DIR_PATH} is missing. This tool wont work.'

def parse_args():
    parser = argparse.ArgumentParser(
        prog='boteval.quickstart',
        description='create example task directory',
         formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('taskdir', metavar='TASKDIR_PATH', type=Path, nargs='?', default=TEMPL_DIR_NAME,
                        help='Output directory where template should be created',
         )
    parser.add_argument('--force', action='store_true',
                        help='overwrite if directory exists')
    args = parser.parse_args()
    return vars(args)

def create_quickstart_dir(taskdir: Path, overwrite=False):
    log.info(f'creating example chat dir at {taskdir}')
    log.info(f'Source {TEMPL_DIR_PATH}')
    if not taskdir.exists():
        taskdir.mkdir(parents=True)
    else:
        if overwrite:
            log.warning(f'{taskdir} exists and going to overwrite it')
        else:
            raise Exception(f'{taskdir} already exists. set argument --force to overwrite')

    for src_path in TEMPL_DIR_PATH.iterdir():
        if src_path.is_dir():
            log.warning(f'skipping {src_path}')
            continue
        dst_path = taskdir / src_path.name
        log.info(f'Creating {dst_path}')
        shutil.copy(src_path, dst_path)


def main(**args):
    args = args or parse_args()
    create_quickstart_dir(taskdir=args['taskdir'], overwrite=args['force'])


if '__main__' == __name__:
    main()
