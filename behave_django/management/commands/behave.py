from __future__ import absolute_import

import sys

from behave.__main__ import main as behave_main
from behave.configuration import options as behave_options
from behave.configuration import valid_python_module
from django.core.management.base import BaseCommand

from behave_django.environment import monkey_patch_behave
from behave_django.runner import (
    BehaviorDrivenTestRunner,
    ExistingDatabaseTestRunner,
    SimpleTestRunner,
)


def add_command_arguments(parser):
    """
    Additional command line arguments for the behave management command
    """
    parser.add_argument(
        '--noinput',
        '--no-input',
        action='store_const',
        const=False,
        dest='interactive',
        help='Tells Django to NOT prompt the user for input of any kind.',
    )
    parser.add_argument(
        '--failfast', action='store_const', const=True, dest='failfast',
        help=('Tells Django to stop running the '
              'test suite after first failed test.'),
    )
    parser.add_argument(
        '--reverse', action='store_const', const=True, dest='reverse',
        help='Reverses test cases order.',
    )
    parser.add_argument(
        '--use-existing-database',
        action='store_true',
        default=False,
        help="Don't create a test database. USE AT YOUR OWN RISK!",
    )
    parser.add_argument(
        '-k', '--keepdb',
        action='store_const',
        const=True,
        help="Preserves the test DB between runs.",
    )
    parser.add_argument(
        '-S', '--simple',
        action='store_true',
        default=False,
        help="Use simple test runner that supports Django's"
        " testing client only (no web browser automation)"
    )
    parser.add_argument(
        '--runner-class',
        action='store',
        type=valid_python_module,
        default='behave_django.runner.BehaviorDrivenTestRunner',
        help=('Full Python dotted path to a package, module, Django '
              'TestRunner.  Defaults to "%(default)s)".')
    )


def add_behave_arguments(parser):  # noqa
    """
    Additional command line arguments extracted directly from behave
    """

    # Option strings that conflict with Django
    conflicts = [
        '--no-color',
        '--version',
        '-c',
        '-k',
        '-v',
        '-S',
        '--simple',
        '--runner-class',
    ]

    parser.add_argument(
        'paths',
        action='store',
        nargs='*',
        help="Feature directory, file or file location (FILE:LINE)."
    )

    for fixed, keywords in behave_options:
        keywords = keywords.copy()

        # Configfile only entries are ignored
        if not fixed:
            continue

        # Build option strings
        option_strings = []
        for option in fixed:
            # Prefix conflicting option strings with `--behave`
            if option in conflicts:
                prefix = '--' if option.startswith('--') else '-'
                option = option.replace(prefix, '--behave-', 1)

            option_strings.append(option)

        # config_help isn't a valid keyword for add_argument
        if 'config_help' in keywords:
            keywords['help'] = keywords['config_help']
            del keywords['config_help']

        parser.add_argument(*option_strings, **keywords)


class Command(BaseCommand):
    help = 'Runs behave tests'

    def add_arguments(self, parser):
        """
        Add behave's and our command line arguments to the command
        """
        parser.usage = "%(prog)s [options] [ [DIR|FILE|FILE:LINE] ]+"
        parser.description = """\
        Run a number of feature tests with behave."""

        add_command_arguments(parser)
        add_behave_arguments(parser)

    def handle(self, *args, **options):

        django_runner_class = options['runner_class']
        is_default_runner = django_runner_class is BehaviorDrivenTestRunner

        # Check the flags
        if options['use_existing_database'] and options['simple']:
            self.stderr.write(self.style.WARNING(
                '--simple flag has no effect'
                ' together with --use-existing-database'
            ))

        active_flags = options['use_existing_database'] or options['simple']
        if not is_default_runner and active_flags:
            self.stderr.write(self.style.WARNING(
                '--use-existing-database or --simple has no effect'
                ' together with --runner-class'
            ))

        # Configure django environment
        passthru_args = ('failfast',
                         'interactive',
                         'keepdb',
                         'reverse')
        runner_args = {k: v for
                       k, v in
                       options.items() if k in passthru_args and v is not None}

        if is_default_runner:
            if options['dry_run'] or options['use_existing_database']:
                django_runner_class = ExistingDatabaseTestRunner
            elif options['simple']:
                django_runner_class = SimpleTestRunner

        django_test_runner = django_runner_class(**runner_args)
        django_test_runner.setup_test_environment()

        old_config = django_test_runner.setup_databases()

        # Run Behave tests
        monkey_patch_behave(django_test_runner)
        behave_args = self.get_behave_args()
        exit_status = behave_main(args=behave_args)

        # Teardown django environment
        django_test_runner.teardown_databases(old_config)
        django_test_runner.teardown_test_environment()

        if exit_status != 0:
            sys.exit(exit_status)

    def get_behave_args(self, argv=sys.argv):
        """
        Get a list of those command line arguments specified with the
        management command that are meant as arguments for running behave.
        """
        parser = BehaveArgsHelper().create_parser('manage.py', 'behave')
        args, unknown = parser.parse_known_args(argv[2:])

        behave_args = []
        for option in unknown:
            # Remove behave prefix
            if option.startswith('--behave-'):
                option = option.replace('--behave-', '', 1)
                prefix = '-' if len(option) == 1 else '--'
                option = prefix + option

            behave_args.append(option)

        return behave_args


class BehaveArgsHelper(Command):

    def add_arguments(self, parser):
        """
        Override setup of command line arguments to make behave commands not
        be recognized. The unrecognized args will then be for behave! :)
        """
        add_command_arguments(parser)
