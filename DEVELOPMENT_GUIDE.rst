DEVELOPMENT GUIDE
=================

**Welcome hacker!**

This document will make your life easier by helping you setup a development environment, IDEs, tests, coding practices,
or anything that will help you be more productive. If you found something is missing or inaccurate, update this guide
and send a Pull Request.

Environment Setup
-----------------

.. note:: You need to have `pyenv`_ installed, please see the `installation instructions`_ for more information.

``make setup`` will perform the following steps for you. You can either run ``make setup`` command or perform the
steps manually.

1. Install Python Versions
~~~~~~~~~~~~~~~~~~~~~~~~~~
Python 2.7 is our officially supported Python version. We have a future goal to support to Python3.6 but the code base
currently does not work with Python3. To make future migration easier, any new code we write must be compatible with
Python3. Follow the idioms from this `excellent cheatsheet`_ to make sure your code is compatible with both Python
versions.

Setup Python locally using `pyenv`_

#. Install PyEnv - ``curl -L https://github.com/pyenv/pyenv-installer/raw/master/bin/pyenv-installer | bash``
#. ``pyenv install 2.7.14``
#. Make the Python version available in the project: ``pyenv local 2.7.14``


2. Activate Virtualenv
~~~~~~~~~~~~~~~~~~~~~~
Virtualenv allows you to install required libraries outside of the Python installation. A good practice is to setup
a different virtualenv for each project. `pyenv`_ comes with a handy plugin that can create virtualenv.

#. Create new virtualenv if it does not exist: ``pyenv virtualenv 2.7.14 samtranslator27``
#. ``pyenv activate samtranslator27``
#. [Optional] Automatically activate the virtualenv in for this folder: ``pyenv local samtranslator27``


3. Install dependencies
~~~~~~~~~~~~~~~~~~~~~~~
Install dependencies by running the following command. Make sure the Virtualenv you created above is active.

``pip install -r requirements/base.txt -r requirements/dev.txt``


Running Tests
-------------

Unit tests
~~~~~~~~~~

``make test`` command will run all unit tests. This command is configured to fail when code coverage for package
drops below 95%.

``pytest -k "TestMyClass"`` command will run all unit tests within the `TestMyClass` class.

Pull Requests
-------------
Before sending pull requests make sure to run ``make pr`` command. This will run unit tests, linters, and static
analysis tools to verify that your code changes follow the coding standards required by this package.

It will also fail if unit test coverage drops below 95%. All new code that you write must have 100% unit test coverage.
This might sound over-ambitious, especially if you come from Java world, but with Python this is actually realistic.
In Python, if you do not test a piece of code, there is zero confidence that the code will ever work in the future.
Tests are also a documentation of the success and failure cases, which is crucial when refactoring code in future.


.. _excellent cheatsheet: http://python-future.org/compatible_idioms.html
.. _pyenv: https://github.com/pyenv/pyenv
.. _tox: http://tox.readthedocs.io/en/latest/
.. _installation instructions: https://github.com/pyenv/pyenv#installation

Profiling
---------

Install snakeviz `pip install snakeviz`

```
python -m cProfile -o sam_profile_results bin/sam-translate.py translate --input-file=tests/translator/input/alexa_skill.yaml --output-file=cfn-template.json
snakeviz sam_profile_results
```

Verifying transforms
--------------------

If you make changes to the transformer and want to verify the resulting CloudFormation template works as expected, you can transform your SAM template into a CloudFormation template using the following process:

```shell
# Optional: You only need to run the package command in certain cases; e.g. when your CodeUri specifies a local path
# Replace MY_TEMPLATE_PATH with the path to your template and MY_S3_BUCKET with an existing S3 bucket
aws cloudformation package --template-file MY_TEMPLATE_PATH/template.yaml --output-template-file output-template.yaml --s3-bucket MY_S3_BUCKET

# Transform your SAM template into a CloudFormation template
# Replace "output-template.yaml" if you didn't run the package command above or specified a different path for --output-template-file
bin/sam-translate.py --input-file=output-template.yaml

# Deploy your transformed CloudFormation template
# Replace MY_STACK_NAME with a unique name each time you deploy
aws cloudformation deploy --template-file cfn-template.json --capabilities CAPABILITY_NAMED_IAM --stack-name MY_STACK_NAME
```