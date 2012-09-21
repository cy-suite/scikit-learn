"""
Small example showing recursive logging in an object hierarchy.
"""

from time import sleep
import itertools

from sklearn.progress_logger import HasLogger
from sklearn.externals.joblib import Parallel, delayed

FIRST_NAMES = itertools.cycle(['Jane', 'Joe', 'Jack'])

def do_work(logger, msg):
    logger.progress('Working', short_message=msg)


class Employee(HasLogger):

    def __init__(self, name='Joe Average', verbose=False):
        self.name = name
        self.verbose = verbose

    def work(self, chore_msg):
        log = self._get_logger()
        sleep(.2)
        Parallel(n_jobs=-1)(delayed(do_work)(log, '.')
                for _ in range(10))
        log.progress('%s says "Done my chores %s"',
                     self.name, chore_msg)


class Boss(HasLogger):

    def __init__(self, n_employees=3, verbose=False):
        self.verbose = verbose
        self.n_employees = n_employees

    def yell(self):
        log = self._get_logger()
        log.progress('Get to work!!')
        employes = [Employee(name='%s Average' % n,
                            verbose=log.clone())
                    for _, n in zip(range(self.n_employees),
                                 FIRST_NAMES)]

        for employe in employes:
            employe.work('code')


if __name__ == '__main__':
    boss = Boss(verbose=2)
    boss.yell()

    from sklearn.progress_logger import setup_logger
    import logging
    setup_logger('__main__', level=logging.DEBUG, display_name=True,
              time_stamp=True)
    boss.yell()
