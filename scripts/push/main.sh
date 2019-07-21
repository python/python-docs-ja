#!/bin/bash
set -eux

bash ${TRAVIS_BUILD_DIR}/scripts/${build_type}/prepare-build_3.7
bash ${TRAVIS_BUILD_DIR}/scripts/${build_type}/upload-catalog
bash ${TRAVIS_BUILD_DIR}/scripts/${build_type}/renew-catalog-template
