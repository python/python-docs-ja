#!/bin/sh
# Pull catalog message files from Transifex

[ -n "$GITHUB_ACTIONS" ] && set -x
set -e

# Allow language being passed as 1st argument, defaults to ja
LANGUAGE=${1:-ja}

ROOTDIR=$(realpath "$(dirname "$0")/..")

cd "${ROOTDIR}"

if ! test -f cpython/Doc/conf.py; then
  echo Unable to find proper CPython Doc folder
  exit 1
fi

# Use fresh catalogs so renamed or removed resources cannot survive a prior run.
mkdir -p cpython/Doc/locales
WORKDIR=$(mktemp -d "${ROOTDIR}/cpython/Doc/locales/update.XXXXXX")
trap 'rm -rf "$WORKDIR"' EXIT
trap 'exit 1' HUP INT TERM

# Create POT Files
cd cpython/Doc
sphinx-build -E -b gettext -D gettext_compact=0 -d "${WORKDIR}/.doctrees" . "${WORKDIR}/pot"

# Generate a fresh .tx/config from the current POT files.
cd "${WORKDIR}"
sphinx-intl create-txconfig
sphinx-intl update-txconfig-resources -p pot -d . --transifex-organization-name python-doc --transifex-project-name python-newest

# Pull translations into the temporary LANGUAGE/LC_MESSAGES directory.
tx pull -l "${LANGUAGE}" -t --use-git-timestamps

# Validate the download before copying catalogs or removing obsolete files.
python "${ROOTDIR}/scripts/translations.py" sync "${WORKDIR}" "${ROOTDIR}" --language "${LANGUAGE}"
