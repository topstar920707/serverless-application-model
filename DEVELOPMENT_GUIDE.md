DEVELOPMENT GUIDE
=================

**Welcome hacker!**

This document will make your life easier by helping you setup a
development environment, IDEs, tests, coding practices, or anything that
will help you be more productive. If you found something is missing or
inaccurate, update this guide and send a Pull Request.

**Note**: `pyenv` currently only supports macOS and Linux. If you are a
Windows users, consider using [pipenv](https://docs.pipenv.org/).

1-Click Ready to Hack IDE
-------------------------
For setting up a local development environment, we recommend using Gitpod - a service that allows you to spin up an in-browser Visual Studio Code-compatible editor, with everything set up and ready to go for development on this project. Just click the button below to create your private workspace:

[![Gitpod ready-to-code](https://img.shields.io/badge/Gitpod-ready--to--code-blue?logo=gitpod)](https://gitpod.io/#https://github.com/awslabs/aws-sam-cli)

This will start a new Gitpod workspace, and immediately kick off a build of the code. Once it's done, you can start working.

Gitpod is free for 50 hours per month - make sure to stop your workspace when you're done (you can always resume it later, and it won't need to run the build again).


Environment Setup
-----------------
### 1. Install Python Versions

Our officially supported Python versions are 2.7, 3.6, 3.7 and 3.8. Follow the idioms from this [excellent cheatsheet](http://python-future.org/compatible_idioms.html) to
make sure your code is compatible with both Python 2.7 and 3 (>=3.6) versions.
Our CI/CD pipeline is setup to run unit tests against both Python 2.7 and 3 versions. So make sure you test it with both versions before sending a Pull Request.
See [Unit testing with multiple Python versions](#unit-testing-with-multiple-python-versions).

[pyenv](https://github.com/pyenv/pyenv) is a great tool to
easily setup multiple Python versions. For 

> Note: For Windows, type
> `export PATH="/c/Users/<user>/.pyenv/libexec:$PATH"` to add pyenv to
> your path.

1.  Install PyEnv -
    `curl -L https://github.com/pyenv/pyenv-installer/raw/master/bin/pyenv-installer | bash`
1. Restart shell so the path changes take effect - `exec $SHELL`
1.  `pyenv install 2.7.17`
1.  `pyenv install 3.6.12`
1.  `pyenv install 3.7.9`
1.  `pyenv install 3.8.6`
1.  Make Python versions available in the project:
    `pyenv local 2.7.17 3.6.12 3.7.9 3.8.6`

Note: also make sure the following lines were written into your `.bashrc` (or `.zshrc`, depending on which shell you are using):
```
export PATH="$HOME/.pyenv/bin:$PATH"
eval "$(pyenv init -)"
eval "$(pyenv virtualenv-init -)"
```

### 2. Install Additional Tooling
#### Black
We format our code using [Black](https://github.com/python/black) and verify the source code is black compliant
during PR checks. Black will be installed automatically with `make init`.

After installing, you can run our formatting through our Makefile by `make black` or integrating Black directly in your favorite IDE (instructions
can be found [here](https://black.readthedocs.io/en/stable/editor_integration.html))
 
##### (workaround) Integrating Black directly in your favorite IDE
Since black is installed in virtualenv, when you follow [this instruction](https://black.readthedocs.io/en/stable/editor_integration.html), `which black` might give you this

```bash
(sam37) $ where black
/Users/<username>/.pyenv/shims/black
```

However, IDEs such PyChaim (using FileWatcher) will have a hard time invoking `/Users/<username>/.pyenv/shims/black` 
and this will happen:

```
pyenv: black: command not found

The `black' command exists in these Python versions:
  3.7.9/envs/sam37
  sam37
``` 

A simple workaround is to use `/Users/<username>/.pyenv/versions/sam37/bin/black` 
instead of `/Users/<username>/.pyenv/shims/black`.

#### Pre-commit
If you don't wish to manually run black on each pr or install black manually, we have integrated black into git hooks through [pre-commit](https://pre-commit.com/).
After installing pre-commit, run `pre-commit install` in the root of the project. This will install black for you and run the black formatting on
commit.

### 3. Activate Virtualenv

Virtualenv allows you to install required libraries outside of the
Python installation. A good practice is to setup a different virtualenv
for each project. [pyenv](https://github.com/pyenv/pyenv) comes with a
handy plugin that can create virtualenv.

Depending on the python version, the following commands would change to
be the appropriate python version.

1.  Create Virtualenv `sam37` for Python3.7: `pyenv virtualenv 3.7.9 sam37`
1.  Activate Virtualenv: `pyenv activate sam37`

### 4. Install dev version of SAM Translator

We will install a development version of SAM Translator from source into the
virtualenv.

1.  Activate Virtualenv: `pyenv activate sam37`
1.  Install dev version of SAM Translator: `make init`

Running Tests
-------------

### Unit testing with one Python version

If you're trying to do a quick run, it's ok to use the current python version.  Run `make pr`.
If you're using Python2.7, you can run `make pr2.7` instead.

### Unit testing with multiple Python versions

Currently, our officially supported Python versions are 2.7, 3.6, 3.7 and 3.8. For the most
part, code that works in Python3.6 will work in Python3.7 and Python3.8. You only run into problems if you are
trying to use features released in a higher version (for example features introduced into Python3.7
will not work in Python3.6). If you want to test in many versions, you can create a virtualenv for
each version and flip between them (sourcing the activate script). Typically, we run all tests in
one python version locally and then have our ci (appveyor) run all supported versions.

### Integration tests

Integration tests are covered in detail in the [INTEGRATION_TESTS.md file](INTEGRATION_TESTS.md) of this repository.

Code Conventions
----------------

Please follow these code conventions when making your changes. This will
align your code to the same conventions used in rest of the package and
make it easier for others to read/understand your code. Some of these
conventions are best practices that we have learnt over time.

-   Don\'t write any code in `__init__.py` file unless there is a really strong reason.
-   Module-level logger variable must be named as `LOG`
-   If your method wants to report a failure, it *must* raise a custom
    exception. Built-in Python exceptions like `TypeError`, `KeyError`
    are raised by Python interpreter and usually signify a bug in your
    code. Your method must not explicitly raise these exceptions because
    the caller has no way of knowing whether it came from a bug or not.
    Custom exceptions convey are must better at conveying the intent and
    can be handled appropriately by the caller. In HTTP lingo, custom
    exceptions are equivalent to 4xx (user\'s fault) and built-in
    exceptions are equivalent to 5xx (Service Fault)
-   Don't use `*args` or `**kwargs` unless there is a really strong
    reason to do so. You must explain the reason in great detail in
    docstrings if you were to use them.
-   Do not catch the broader `Exception`, unless you have a really
    strong reason to do. You must explain the reason in great detail in
    comments.

Profiling
---------

Install snakeviz: `pip install snakeviz`

```bash
python -m cProfile -o sam_profile_results bin/sam-translate.py translate --template-file=tests/translator/input/alexa_skill.yaml --output-template=cfn-template.json
snakeviz sam_profile_results
```

Verifying transforms
--------------------

If you make changes to the transformer and want to verify the resulting CloudFormation template works as expected, you can transform your SAM template into a CloudFormation template using the following process:

```bash
# Optional: You only need to run the package command in certain cases; e.g. when your CodeUri specifies a local path
# Replace MY_TEMPLATE_PATH with the path to your template and MY_S3_BUCKET with an existing S3 bucket
aws cloudformation package --template-file MY_TEMPLATE_PATH/template.yaml --output-template-file output-template.yaml --s3-bucket MY_S3_BUCKET

# Transform your SAM template into a CloudFormation template
# Replace "output-template.yaml" if you didn't run the package command above or specified a different path for --output-template-file
bin/sam-translate.py --template-file=output-template.yaml

# Deploy your transformed CloudFormation template
# Replace MY_STACK_NAME with a unique name each time you deploy
aws cloudformation deploy --template-file cfn-template.json --capabilities CAPABILITY_NAMED_IAM --stack-name MY_STACK_NAME
   ```