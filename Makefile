UV ?= uv
RUNS ?= runs
TF_DIR := deploy/terraform
COMPOSE := docker compose -f deploy/docker-compose.yml
LOCALSTACK_PORT ?= 4566
# The Lambda runtime in deploy/terraform is python3.12 and the function declares
# architectures = ["x86_64"]; the bundle is resolved for that platform whatever the host is
# (aarch64-manylinux2014 with architectures = ["arm64"] also works, changed in both places).
LAMBDA_PLATFORM ?= x86_64-manylinux2014
LAMBDA_IMAGE ?= python:3.12-slim
export LOCALSTACK_PORT

.PHONY: setup lint test tf-validate demo demo-review stack-up stack-down tf-apply-local tf-destroy-local lambda-zip lambda-check clean

setup:
	$(UV) sync --python 3.12 --extra dev

lint:
	$(UV) run ruff check .
	$(UV) run ruff format --check .

test:
	$(UV) run pytest -q

tf-validate:
	terraform -chdir=$(TF_DIR) fmt -check -recursive
	terraform -chdir=$(TF_DIR) init -backend=false -input=false >/dev/null
	terraform -chdir=$(TF_DIR) validate

demo:
	RUNS=$(RUNS) scripts/demo.sh

demo-review:
	RUNS=$(RUNS) scripts/demo-review.sh

stack-up:
	$(COMPOSE) up -d localstack

stack-down:
	$(COMPOSE) down

tf-apply-local:
	terraform -chdir=$(TF_DIR) init -input=false >/dev/null
	terraform -chdir=$(TF_DIR) apply -input=false -auto-approve -var-file=localstack.tfvars -var localstack_endpoint=http://localhost:$(LOCALSTACK_PORT)

tf-destroy-local:
	terraform -chdir=$(TF_DIR) destroy -input=false -auto-approve -var-file=localstack.tfvars -var localstack_endpoint=http://localhost:$(LOCALSTACK_PORT)

lambda-zip:
	rm -rf build/lambda build/wheel && mkdir -p build/lambda build/wheel
	$(UV) export --frozen --no-dev --no-emit-project --no-hashes --output-file build/lambda-requirements.txt --quiet
	$(UV) build --wheel --out-dir build/wheel --quiet
	$(UV) pip install --quiet --python 3.12 --python-platform $(LAMBDA_PLATFORM) --only-binary :all: --no-deps \
		--target build/lambda --requirements build/lambda-requirements.txt build/wheel/playbook-*.whl
	cp deploy/lambda/handler.py build/lambda/
	cp -R procedures build/lambda/procedures
	@echo "built build/lambda for $(LAMBDA_PLATFORM) from uv.lock; apply with: terraform -chdir=$(TF_DIR) apply -var lambda_source_dir=$(PWD)/build/lambda"

lambda-check:
	# Import the bundle under the target platform's python3.12 in Docker (the bundle is streamed in
	# as a tar so the check does not depend on bind mounts).
	COPYFILE_DISABLE=1 tar --no-xattrs -C build/lambda -cf - . | docker run --rm -i --platform linux/amd64 $(LAMBDA_IMAGE) \
		sh -c 'mkdir -p /var/task && tar -xf - -C /var/task && cd /var/task && python -c "import platform, handler, pydantic_core, jiter, anthropic, boto3; print(\"handler imports on\", platform.machine(), \"python\", platform.python_version(), \"anthropic\", anthropic.__version__)"'

clean:
	rm -rf $(RUNS) build dist .pytest_cache .ruff_cache $(TF_DIR)/.build
