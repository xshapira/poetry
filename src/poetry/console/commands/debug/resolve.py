from __future__ import annotations

from typing import TYPE_CHECKING

from cleo.helpers import argument
from cleo.helpers import option
from cleo.io.outputs.output import Verbosity

from poetry.console.commands.init import InitCommand


if TYPE_CHECKING:
    from poetry.console.commands.show import ShowCommand


class DebugResolveCommand(InitCommand):

    name = "debug resolve"
    description = "Debugs dependency resolution."

    arguments = [
        argument("package", "The packages to resolve.", optional=True, multiple=True)
    ]
    options = [
        option(
            "extras",
            "E",
            "Extras to activate for the dependency.",
            flag=False,
            multiple=True,
        ),
        option("python", None, "Python version(s) to use for resolution.", flag=False),
        option("tree", None, "Display the dependency tree."),
        option("install", None, "Show what would be installed for the current system."),
    ]

    loggers = ["poetry.repositories.pypi_repository", "poetry.inspection.info"]

    def handle(self) -> int:
        from cleo.io.null_io import NullIO
        from poetry.core.packages.project_package import ProjectPackage

        from poetry.factory import Factory
        from poetry.puzzle import Solver
        from poetry.repositories.pool import Pool
        from poetry.repositories.repository import Repository
        from poetry.utils.env import EnvManager

        if packages := self.argument("package"):
            # Using current pool for determine_requirements()
            self._pool = self.poetry.pool

            package = ProjectPackage(
                self.poetry.package.name, self.poetry.package.version
            )

            # Silencing output
            verbosity = self.io.output.verbosity
            self.io.output.set_verbosity(Verbosity.QUIET)

            requirements = self._determine_requirements(packages)

            self.io.output.set_verbosity(verbosity)

            for constraint in requirements:
                name = constraint.pop("name")
                extras = []
                for extra in self.option("extras"):
                    if " " in extra:
                        extras += [e.strip() for e in extra.split(" ")]
                    else:
                        extras.append(extra)

                constraint["extras"] = extras

                package.add_dependency(Factory.create_dependency(name, constraint))

        else:
            package = self.poetry.package
        package.python_versions = self.option("python") or (
            self.poetry.package.python_versions
        )

        pool = self.poetry.pool

        solver = Solver(package, pool, Repository(), Repository(), self._io)

        ops = solver.solve().calculate_operations()

        self.line("")
        self.line("Resolution results:")
        self.line("")

        if self.option("tree"):
            show_command: ShowCommand = self.application.find("show")
            show_command.init_styles(self.io)

            packages = [op.package for op in ops]
            repo = Repository(packages=packages)

            requires = package.all_requires
            for pkg in repo.packages:
                for require in requires:
                    if pkg.name == require.name:
                        show_command.display_package_tree(self.io, pkg, repo)
                        break

            return 0

        table = self.table(style="compact")
        table.style.set_vertical_border_chars("", " ")
        rows = []

        if self.option("install"):
            env = EnvManager(self.poetry).get()
            pool = Pool()
            locked_repository = Repository()
            for op in ops:
                locked_repository.add_package(op.package)

            pool.add_repository(locked_repository)

            solver = Solver(package, pool, Repository(), Repository(), NullIO())
            with solver.use_environment(env):
                ops = solver.solve().calculate_operations()

        for op in ops:
            if self.option("install") and op.skipped:
                continue

            pkg = op.package
            row = [
                f"<c1>{pkg.complete_name}</c1>",
                f"<b>{pkg.version}</b>",
            ]

            if not pkg.marker.is_any():
                row[2] = str(pkg.marker)

            rows.append(row)

        table.set_rows(rows)
        table.render()

        return 0
