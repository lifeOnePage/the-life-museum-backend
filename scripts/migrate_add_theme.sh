#!/bin/bash
# records 테이블에 theme 컬럼을 추가하는 마이그레이션 실행 스크립트
# 실행 방법: bash scripts/migrate_add_theme.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "마이그레이션 실행: add theme to records (c2d3e4f5a6b7)"
alembic upgrade c2d3e4f5a6b7
echo "완료"
