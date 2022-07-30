from __future__ import annotations

import os
import re
import sys
import urllib.parse

from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import Mapping

from cleo.helpers import option
from tomlkit import inline_table

from poetry.console.commands.command import Command
from poetry.console.commands.env_command import EnvCommand
from poetry.utils.helpers import canonicalize_name


if TYPE_CHECKING:
    from poetry.core.packages.package import Package
    from tomlkit.items import InlineTable

    from poetry.repositories import Pool


class InitCommand(Command):
    name = "init"
    description = (
        "Creates a basic <comment>pyproject.toml</> file in the current directory."
    )

    options = [
        option("name", None, "Name of the package.", flag=False),
        option("description", None, "Description of the package.", flag=False),
        option("author", None, "Author name of the package.", flag=False),
        option("python", None, "Compatible Python versions.", flag=False),
        option(
            "dependency",
            None,
            "Package to require, with an optional version constraint, "
            "e.g. requests:^2.10.0 or requests=2.11.1.",
            flag=False,
            multiple=True,
        ),
        option(
            "dev-dependency",
            None,
            "Package to require for development, with an optional version constraint, "
            "e.g. requests:^2.10.0 or requests=2.11.1.",
            flag=False,
            multiple=True,
        ),
        option("license", "l", "License of the package.", flag=False),
    ]

    help = """\
The <c1>init</c1> command creates a basic <comment>pyproject.toml</> file in the\
 current directory.
"""

    def __init__(self) -> None:
        super().__init__()

        self._pool: Pool | None = None

    def handle(self) -> int:
        from pathlib import Path

        from poetry.core.pyproject.toml import PyProjectTOML
        from poetry.core.vcs.git import GitConfig

        from poetry.layouts import layout
        from poetry.utils.env import SystemEnv

        pyproject = PyProjectTOML(Path.cwd() / "pyproject.toml")

        if pyproject.file.exists():
            if pyproject.is_poetry_project():
                self.line_error(
                    "<error>A pyproject.toml file with a poetry section already"
                    " exists.</error>"
                )
                return 1

            if pyproject.data.get("build-system"):
                self.line_error(
                    "<error>A pyproject.toml file with a defined build-system already"
                    " exists.</error>"
                )
                return 1

        vcs_config = GitConfig()

        if self.io.is_interactive():
            self.line("")
            self.line(
                "This command will guide you through creating your"
                " <info>pyproject.toml</> config."
            )
            self.line("")

        name = self.option("name")
        if not name:
            name = Path.cwd().name.lower()

            question = self.create_question(
                f"Package name [<comment>{name}</comment>]: ", default=name
            )
            name = self.ask(question)

        version = "0.1.0"
        question = self.create_question(
            f"Version [<comment>{version}</comment>]: ", default=version
        )
        version = self.ask(question)

        description = self.option("description") or ""
        question = self.create_question(
            f"Description [<comment>{description}</comment>]: ",
            default=description,
        )
        description = self.ask(question)

        author = self.option("author")
        if not author and vcs_config and vcs_config.get("user.name"):
            author = vcs_config["user.name"]
            if author_email := vcs_config.get("user.email"):
                author += f" <{author_email}>"

        question = self.create_question(
            f"Author [<comment>{author}</comment>, n to skip]: ", default=author
        )
        question.set_validator(lambda v: self._validate_author(v, author))
        author = self.ask(question)

        authors = [author] if author else []
        license = self.option("license") or ""

        question = self.create_question(
            f"License [<comment>{license}</comment>]: ", default=license
        )
        question.set_validator(self._validate_license)
        license = self.ask(question)

        python = self.option("python")
        if not python:
            current_env = SystemEnv(Path(sys.executable))
            default_python = "^" + ".".join(
                str(v) for v in current_env.version_info[:2]
            )
            question = self.create_question(
                f"Compatible Python versions [<comment>{default_python}</comment>]: ",
                default=default_python,
            )
            python = self.ask(question)

        if self.io.is_interactive():
            self.line("")

        requirements = {}
        if self.option("dependency"):
            requirements = self._format_requirements(
                self._determine_requirements(self.option("dependency"))
            )

        question = "Would you like to define your main dependencies interactively?"
        help_message = """\
You can specify a package in the following forms:
  - A single name (<b>requests</b>)
  - A name and a constraint (<b>requests@^2.23.0</b>)
  - A git url (<b>git+https://github.com/python-poetry/poetry.git</b>)
  - A git url with a revision\
 (<b>git+https://github.com/python-poetry/poetry.git#develop</b>)
  - A file path (<b>../my-package/my-package.whl</b>)
  - A directory (<b>../my-package/</b>)
  - A url (<b>https://example.com/packages/my-package-0.1.0.tar.gz</b>)
"""

        help_displayed = False
        if self.confirm(question, True):
            if self.io.is_interactive():
                self.line(help_message)
                help_displayed = True
            requirements.update(
                self._format_requirements(self._determine_requirements([]))
            )
            if self.io.is_interactive():
                self.line("")

        dev_requirements: dict[str, str] = {}
        if self.option("dev-dependency"):
            dev_requirements = self._format_requirements(
                self._determine_requirements(self.option("dev-dependency"))
            )

        question = (
            "Would you like to define your development dependencies interactively?"
        )
        if self.confirm(question, True):
            if self.io.is_interactive() and not help_displayed:
                self.line(help_message)

            dev_requirements.update(
                self._format_requirements(self._determine_requirements([]))
            )
            if self.io.is_interactive():
                self.line("")

        layout_ = layout("standard")(
            name,
            version,
            description=description,
            author=authors[0] if authors else None,
            license=license,
            python=python,
            dependencies=requirements,
            dev_dependencies=dev_requirements,
        )

        content = layout_.generate_poetry_content(original=pyproject)
        if self.io.is_interactive():
            self.line("<info>Generated file</info>")
            self.line("")
            self.line(content)
            self.line("")

        if not self.confirm("Do you confirm generation?", True):
            self.line_error("<error>Command aborted</error>")

            return 1

        with (Path.cwd() / "pyproject.toml").open("w", encoding="utf-8") as f:
            f.write(content)

        return 0

    def _generate_choice_list(
        self, matches: list[Package], canonicalized_name: str
    ) -> list[str]:
        choices = []
        matches_names = [p.name for p in matches]
        exact_match = canonicalized_name in matches_names
        if exact_match:
            choices.append(matches[matches_names.index(canonicalized_name)].pretty_name)

        for found_package in matches:
            if len(choices) >= 10:
                break

            if found_package.name == canonicalized_name:
                continue

            choices.append(found_package.pretty_name)

        return choices

    def _determine_requirements(
        self,
        requires: list[str],
        allow_prereleases: bool = False,
        source: str | None = None,
    ) -> list[dict[str, str | list[str]]]:
        if not requires:
            requires = []

            package = self.ask(
                "Search for package to add (or leave blank to continue):"
            )
            while package:
                constraint = self._parse_requirements([package])[0]
                if (
                    "git" in constraint
                    or "url" in constraint
                    or "path" in constraint
                    or "version" in constraint
                ):
                    self.line(f"Adding <info>{package}</info>")
                    requires.append(constraint)
                    package = self.ask("\nAdd a package:")
                    continue

                canonicalized_name = canonicalize_name(constraint["name"])
                if matches := self._get_pool().search(canonicalized_name):
                    choices = self._generate_choice_list(matches, canonicalized_name)

                    info_string = (
                        f"Found <info>{len(matches)}</info> packages matching"
                        f" <c1>{package}</c1>"
                    )

                    if len(matches) > 10:
                        info_string += "\nShowing the first 10 matches"

                    self.line(info_string)

                    package = self.choice(
                        "\nEnter package # to add, or the complete package name if it"
                        " is not listed",
                        choices,
                        attempts=3,
                    )

                    # package selected by user, set constraint name to package name
                    if package is not False:
                        constraint["name"] = package

                else:
                    self.line_error("<error>Unable to find package</error>")
                    package = False
                # no constraint yet, determine the best version automatically
                if package is not False and "version" not in constraint:
                    question = self.create_question(
                        "Enter the version constraint to require "
                        "(or leave blank to use the latest version):"
                    )
                    question.attempts = 3
                    question.validator = lambda x: (x or "").strip() or False

                    package_constraint = self.ask(question)

                    if package_constraint is None:
                        _, package_constraint = self._find_best_version_for_package(
                            package
                        )

                        self.line(
                            f"Using version <b>{package_constraint}</b> for"
                            f" <c1>{package}</c1>"
                        )

                    constraint["version"] = package_constraint

                if package is not False:
                    requires.append(constraint)

                if self.io.is_interactive():
                    package = self.ask("\nAdd a package:")

            return requires

        requires = self._parse_requirements(requires)
        result = []
        for requirement in requires:
            if "git" in requirement or "url" in requirement or "path" in requirement:
                result.append(requirement)
                continue
            elif "version" not in requirement:
                # determine the best version automatically
                name, version = self._find_best_version_for_package(
                    requirement["name"],
                    allow_prereleases=allow_prereleases,
                    source=source,
                )
                requirement["version"] = version
                requirement["name"] = name

                self.line(f"Using version <b>{version}</b> for <c1>{name}</c1>")
            else:
                # check that the specified version/constraint exists
                # before we proceed
                name, _ = self._find_best_version_for_package(
                    requirement["name"],
                    requirement["version"],
                    allow_prereleases=allow_prereleases,
                    source=source,
                )

                requirement["name"] = name

            result.append(requirement)

        return result

    def _find_best_version_for_package(
        self,
        name: str,
        required_version: str | None = None,
        allow_prereleases: bool = False,
        source: str | None = None,
    ) -> tuple[str, str]:
        from poetry.version.version_selector import VersionSelector

        selector = VersionSelector(self._get_pool())
        if package := selector.find_best_candidate(
            name,
            required_version,
            allow_prereleases=allow_prereleases,
            source=source,
        ):
            return package.pretty_name, selector.find_recommended_require_version(package)
        else:
            # TODO: find similar
            raise ValueError(f"Could not find a matching version of package {name}")

    def _parse_requirements(self, requirements: list[str]) -> list[dict[str, Any]]:
        from poetry.core.pyproject.exceptions import PyProjectException

        from poetry.puzzle.provider import Provider

        result = []

        try:
            cwd = self.poetry.file.parent
        except (PyProjectException, RuntimeError):
            cwd = Path.cwd()

        for requirement in requirements:
            requirement = requirement.strip()
            extras = []
            if extras_m := re.search(r"\[([\w\d,-_ ]+)\]$", requirement):
                extras = [e.strip() for e in extras_m[1].split(",")]
                requirement, _ = requirement.split("[")

            url_parsed = urllib.parse.urlparse(requirement)
            if url_parsed.scheme and url_parsed.netloc:
                # Url
                if url_parsed.scheme in ["git+https", "git+ssh"]:
                    from poetry.core.vcs.git import Git
                    from poetry.core.vcs.git import ParsedUrl

                    parsed = ParsedUrl.parse(requirement)
                    url = Git.normalize_url(requirement)

                    pair = {"name": parsed.name, "git": url.url}
                    if parsed.rev:
                        pair["rev"] = url.revision

                    if extras:
                        pair["extras"] = extras

                    package = Provider.get_package_from_vcs(
                        "git", url.url, rev=pair.get("rev")
                    )
                    pair["name"] = package.name
                    result.append(pair)

                    continue
                elif url_parsed.scheme in ["http", "https"]:
                    package = Provider.get_package_from_url(requirement)

                    pair = {"name": package.name, "url": package.source_url}
                    if extras:
                        pair["extras"] = extras

                    result.append(pair)
                    continue
            elif (os.path.sep in requirement or "/" in requirement) and (
                cwd.joinpath(requirement).exists()
                or Path(requirement).expanduser().exists()
                and Path(requirement).expanduser().is_absolute()
            ):
                path = Path(requirement).expanduser()
                is_absolute = path.is_absolute()

                if not path.is_absolute():
                    path = cwd.joinpath(requirement)

                if path.is_file():
                    package = Provider.get_package_from_file(path.resolve())
                else:
                    package = Provider.get_package_from_directory(path.resolve())

                result.append(
                    dict(
                        (
                            [
                                ("name", package.name),
                                (
                                    "path",
                                    path.as_posix()
                                    if is_absolute
                                    else path.relative_to(cwd).as_posix(),
                                ),
                            ]
                            + ([("extras", extras)] if extras else [])
                        )
                    )
                )


                continue

            pair = re.sub(
                "^([^@=: ]+)(?:@|==|(?<![<>~!])=|:| )(.*)$", "\\1 \\2", requirement
            )
            pair = pair.strip()

            require: dict[str, str] = {}
            if " " in pair:
                name, version = pair.split(" ", 2)
                if extras_m := re.search(r"\[([\w\d,-_]+)\]$", name):
                    extras = [e.strip() for e in extras_m[1].split(",")]
                    name, _ = name.split("[")

                require["name"] = name
                if version != "latest":
                    require["version"] = version
            elif m := re.match(
                r"^([^><=!: ]+)((?:>=|<=|>|<|!=|~=|~|\^).*)$", requirement.strip()
            ):
                name, constraint = m[1], m[2]
                if extras_m := re.search(r"\[([\w\d,-_]+)\]$", name):
                    extras = [e.strip() for e in extras_m[1].split(",")]
                    name, _ = name.split("[")

                require["name"] = name
                require["version"] = constraint
            else:
                if extras_m := re.search(r"\[([\w\d,-_]+)\]$", pair):
                    extras = [e.strip() for e in extras_m[1].split(",")]
                    pair, _ = pair.split("[")

                require["name"] = pair

            if extras:
                require["extras"] = extras

            result.append(require)

        return result

    def _format_requirements(
        self, requirements: list[dict[str, str]]
    ) -> Mapping[str, str | Mapping[str, str]]:
        requires = {}
        for requirement in requirements:
            name = requirement.pop("name")
            constraint: str | InlineTable
            if "version" in requirement and len(requirement) == 1:
                constraint = requirement["version"]
            else:
                constraint = inline_table()
                constraint.trivia.trail = "\n"
                constraint.update(requirement)

            requires[name] = constraint

        return requires

    def _validate_author(self, author: str, default: str) -> str | None:
        from poetry.core.packages.package import AUTHOR_REGEX

        author = author or default

        if author in ["n", "no"]:
            return None

        if m := AUTHOR_REGEX.match(author):
            return author
        else:
            raise ValueError(
                "Invalid author string. Must be in the format: "
                "John Smith <john@example.com>"
            )

    def _validate_license(self, license: str) -> str:
        from poetry.core.spdx.helpers import license_by_id

        if license:
            license_by_id(license)

        return license

    def _get_pool(self) -> Pool:
        from poetry.repositories import Pool
        from poetry.repositories.pypi_repository import PyPiRepository

        if isinstance(self, EnvCommand):
            return self.poetry.pool

        if self._pool is None:
            self._pool = Pool()
            self._pool.add_repository(PyPiRepository())

        return self._pool
