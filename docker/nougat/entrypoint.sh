#!/bin/sh
set -eu

for arg in "$@"; do
    case "$arg" in
        --help|-h|--model|-m|--checkpoint|-c)
            exec nougat "$@"
            ;;
    esac
done

exec nougat --model "${NOUGAT_MODEL:-0.1.0-base}" "$@"
