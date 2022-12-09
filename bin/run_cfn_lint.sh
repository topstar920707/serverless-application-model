#!/bin/sh
set -eux

VENV=.venv_cfn_lint

# Install to separate venv to avoid circular dependency; cfn-lint depends on samtranslator
# See https://github.com/aws/serverless-application-model/issues/1042
if [ ! -d "${VENV}" ]; then
    python3 -m venv "${VENV}"
    "${VENV}/bin/python" -m pip install cfn-lint==0.72.2
fi

"${VENV}/bin/cfn-lint"
