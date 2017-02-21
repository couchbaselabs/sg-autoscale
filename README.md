
Scripts and configuration to deploy Couchbase Sync Gateway + Sync Gateway Accelerator to AWS with the ability to scale horizontally via AutoScale Groups.

## Setup direnv

You first need to install [direnv](https://github.com/direnv/direnv)

Create an `.envrc` file with contents:

```
layout python
```

At this point `direnv` should prompt you:

```
direnv: error .envrc is blocked. Run `direnv allow` to approve its content.
```

and you should run:

```
$ direnv allow
```

## Setup Virtualenv

```
$ source setup.sh
```

## Generate cloudformation template

```
$ python src/cloudformation_template.py
```



