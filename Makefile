UV ?= uv
RUNS ?= runs
TF_DIR := deploy/terraform
COMPOSE := docker compose -f deploy/docker-compose.yml

.PHONY: setup lint test tf-validate demo stack-up stack-down tf-apply-local tf-destroy-local lambda-zip clean

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

stack-up:
	$(COMPOSE) up -d localstack

stack-down:
	$(COMPOSE) down

tf-apply-local:
	terraform -chdir=$(TF_DIR) init -input=false >/dev/null
	terraform -chdir=$(TF_DIR) apply -input=false -auto-approve -var-file=localstack.tfvars

tf-destroy-local:
	terraform -chdir=$(TF_DIR) destroy -input=false -auto-approve -var-file=localstack.tfvars

lambda-zip:
	rm -rf build/lambda && mkdir -p build/lambda
	$(UV) pip install --python 3.12 --target build/lambda . >/dev/null
	cp deploy/lambda/handler.py build/lambda/
	cp -R procedures build/lambda/procedures
	@echo "built build/lambda; apply with: terraform -chdir=$(TF_DIR) apply -var lambda_source_dir=$(PWD)/build/lambda"

clean:
	rm -rf $(RUNS) build .pytest_cache .ruff_cache $(TF_DIR)/.build
