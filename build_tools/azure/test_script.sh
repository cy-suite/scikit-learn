#!/bin/bash

set -e

python --version
python -c "import numpy; print('numpy %s' % numpy.__version__)"
python -c "import scipy; print('scipy %s' % scipy.__version__)"
python -c "\
try:
    import pandas
    print('pandas %s' % pandas.__version__)
except ImportError:
    pass
"
python -c "import multiprocessing as mp; print('%d CPUs' % mp.cpu_count())"

run_tests() {
    TEST_DIR="/tmp/sklearn"
    TEST_CMD="pytest --showlocals --durations=20 --pyargs"

    mkdir -p $TEST_DIR
    cp setup.cfg $TEST_DIR
    cd $TEST_DIR

    export SKLEARN_SKIP_NETWORK_TESTS=1

    set -x
    $TEST_CMD sklearn
}


if [[ "$DISTRIB" == "ubuntu" ]]; then
    source deactivate
    source testvenv/bin/activate
fi

run_tests


