#!/bin/bash
set -eux

# clone an additional repository
cd ${GITHUB_WORKSPACE}
git clone --branch ${CATALOG_BRANCH} https://github.com/python-doc-ja/cpython-doc-catalog.git cpython-doc-catalog
mkdir -p ${GITHUB_WORKSPACE}/cpython-doc-catalog/Doc/locales/ja
cd ${GITHUB_WORKSPACE}/cpython-doc-catalog/Doc/locales/ja
ln -s ${GITHUB_WORKSPACE}/python-docs-ja LC_MESSAGES
ls -lF LC_MESSAGES

# upload catalogs to python-docs-ja
cd ${GITHUB_WORKSPACE}/cpython-doc-catalog/Doc/locales
if [ ! -e .tx/config ]; then
  echo ".tx/config does not exist. Skip uploading catalogs to python-docs-ja"
  exit 0
fi

tx pull --force --language ja --parallel
cd ja/LC_MESSAGES
git add *.po **/*.po
git status
if [[ $(git status --short | wc -l) == 0 ]]; then
  echo "no .po file to upload"
else
  echo "I have .po file(s) to upload"
  git commit --message="[skip ci] Update .po files"
  git push --quiet "git@python-docs-ja.github.com:python/python-docs-ja.git" ${DOCS_BRANCH}:${DOCS_BRANCH}
fi
rm -rf ${GITHUB_WORKSPACE}/cpython-doc-catalog/Doc/locales/ja
