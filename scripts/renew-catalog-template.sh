#!/bin/bash
set -eux

# merge from upstream
cd "${BASEDIR}"/cpython-doc-catalog
git remote add upstream https://github.com/python/cpython.git
git remote -v
git fetch --quiet upstream
git merge --no-ff upstream/${CPYTHON_BRANCH} -m "Merge remote-tracking branch 'upstream/${CPYTHON_BRANCH}' into ${CATALOG_BRANCH} by Autobuild bot on TravisCI"

# generate catalog
cd Doc
make build ALLSPHINXOPTS="-E -b gettext -D gettext_compact=0 -d build/.doctrees . locales/pot"
ls -lt locales/pot

# upload catalog templates to cpython-doc-catalog
cd locales
git add pot
git status
if [[ $(git status --short | wc -l) == 0 ]]; then
  echo "no .pot file to update"
  exit 0
fi

echo "I have .pot file(s) to upload"

rm -rf .tx
sphinx-intl create-txconfig
sphinx-intl update-txconfig-resources --transifex-project-name=${TRANSIFEX_PROJECT} --locale-dir . --pot-dir pot
tx push --source --parallel
git add .tx
git commit --message="[skip ci] Update .pot files and .tx/config"
git push --quiet "git@cpython-doc-catalog.github.com:python-doc-ja/cpython-doc-catalog.git" ${CATALOG_BRANCH}:${CATALOG_BRANCH}
