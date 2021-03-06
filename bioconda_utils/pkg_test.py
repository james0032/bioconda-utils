import subprocess as sp
import tempfile
import tarfile
import os
import shlex
import logging

from . import utils

from conda_build.metadata import MetaData

logger = logging.getLogger(__name__)


def get_tests(path):
    "Extract tests from a built package"
    tmp = tempfile.mkdtemp()
    t = tarfile.open(path)
    t.extractall(tmp)
    input_dir = os.path.join(tmp, 'info', 'recipe')

    tests = []
    recipe_meta = MetaData(input_dir)

    tests_commands = recipe_meta.get_value('test/commands')
    tests_imports = recipe_meta.get_value('test/imports')
    requirements = recipe_meta.get_value('requirements/run')

    if tests_imports or tests_commands:
        if tests_commands:
            tests.append(' && '.join(tests_commands))
        if tests_imports and 'python' in requirements:
            tests.append(
                ' && '.join('python -c "import %s"' % imp
                            for imp in tests_imports)
            )
        elif tests_imports and (
            'perl' in requirements or 'perl-threaded' in requirements
        ):
            tests.append(
                ' && '.join('''perl -e "use %s;"''' % imp
                            for imp in tests_imports)
            )

    tests = ' && '.join(tests)
    tests = tests.replace('$R ', 'Rscript ')
    # this is specific to involucro, the way how we build our containers
    tests = tests.replace('$PREFIX', '/usr/local/')
    tests = tests.replace('${PREFIX}', '/usr/local/')

    return tests


def get_image_name(path):
    """
    Returns name of generated docker image.

    Parameters
    ----------

    path : str
        Path to .tar.by2 package build by conda-build

    """
    assert path.endswith('.tar.bz2')

    pkg = os.path.basename(path).replace('.tar.bz2', '')
    toks = pkg.split('-')
    build_string = toks[-1]
    version = toks[-2]
    name = '-'.join(toks[:-2])

    spec = '%s=%s--%s' % (name, version, build_string)
    return spec


def test_package(
    path,
    name_override=None,
    channels=["conda-forge", "defaults"],
    mulled_args="",
    base_image=None
):
    """
    Tests a built package in a minimal docker container.

    Parameters
    ----------
    path : str
        Path to a .tar.bz2 package built by conda-build

    name_override : str
        Passed as the --name-override argument to mulled-build

    channels : None | str | list
        The local channel of the provided package will be added automatically;
        `channels` are channels to use in addition to the local channel.

    mulled_args : str
        Mechanism for passing arguments to the mulled-build command. They will
        be split with shlex.split and passed to the mulled-build command. E.g.,
        mulled_args="--dry-run --involucro-path /opt/involucro"

    base_image : None | str
        Specify custom base image. Busybox is used in the default case.

    """

    assert path.endswith('.tar.bz2'), "Unrecognized path {0}".format(path)
    # assert os.path.exists(path), '{0} does not exist'.format(path)

    conda_bld_dir = os.path.abspath(os.path.dirname(os.path.dirname(path)))

    sp.check_call([utils.bin_for('conda'), 'index', os.path.dirname(path)])
    # always build noarch index to make conda happy
    sp.check_call([utils.bin_for('conda'), 'index', os.path.join(conda_bld_dir, "noarch")])

    spec = get_image_name(path)

    extra_channels = ['file://{0}'.format(conda_bld_dir)]
    if channels is None:
        channels = []
    if isinstance(channels, str):
        channels = [channels]
    extra_channels.extend(channels)
    channel_args = ['--extra-channels', ','.join(extra_channels)]

    tests = get_tests(path)
    logger.debug('Tests to run: %s', tests)

    cmd = [
        'mulled-build',
        'build-and-test',
        spec,
        '-n', 'biocontainers',
        '--test', tests
    ]
    if name_override:
        cmd += ['--name-override', name_override]
    cmd += channel_args
    cmd += shlex.split(mulled_args)
    logger.debug('mulled-build command: %s' % cmd)

    env = os.environ.copy()
    if base_image is not None:
        env["DEST_BASE_IMAGE"] = base_image
    with tempfile.TemporaryDirectory() as d:
        with utils.Progress():
            p = utils.run(cmd, env=env, cwd=d, mask=False)

    return p
