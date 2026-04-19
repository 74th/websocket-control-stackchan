UV ?= uv
PROTO_DIR := protobuf
PROTO_FILE := $(PROTO_DIR)/websocket-message.proto
PY_PROTO_OUT_DIR := stackchan_server/generated_protobuf
FW_PROTO_OUT_DIR := firmware/lib/generated_protobuf
NANOPB_GENERATOR := .pio/libdeps/m5stack-cores3-m5unified/Nanopb/generator/nanopb_generator.py

.PHONY: lint lint-fix protobuf protobuf-python protobuf-firmware clean-protobuf

lint:
	uv run ruff check stackchan_server example_apps
	uv run ty check stackchan_server example_apps

lint-fix:
	uv run ruff check --fix stackchan_server example_apps
	uv run ty check stackchan_server example_apps

protobuf: protobuf-python protobuf-firmware

protobuf-python: $(PROTO_FILE)
	mkdir -p $(PY_PROTO_OUT_DIR)
	touch $(PY_PROTO_OUT_DIR)/__init__.py
	$(UV) run python -m grpc_tools.protoc -I$(PROTO_DIR) --python_out=$(PY_PROTO_OUT_DIR) $(PROTO_FILE)

protobuf-firmware: $(PROTO_FILE)
	@test -f $(NANOPB_GENERATOR) || (echo "nanopb generator not found: $(NANOPB_GENERATOR)" && exit 1)
	mkdir -p $(FW_PROTO_OUT_DIR)
	$(UV) run python $(NANOPB_GENERATOR) --proto-path=$(PROTO_DIR) --output-dir=$(FW_PROTO_OUT_DIR) $(PROTO_FILE)

clean-protobuf:
	rm -f $(PY_PROTO_OUT_DIR)/websocket_message_pb2.py
	rm -f stackchan_server/generated/websocket_message_pb2.py
	rm -f $(FW_PROTO_OUT_DIR)/websocket-message.pb.h $(FW_PROTO_OUT_DIR)/websocket-message.pb.c
