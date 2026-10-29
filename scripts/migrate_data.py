#!/usr/bin/env python3
"""
Obrigado - Data Migration, Backup & Encryption CLI Utility
Enables automated and on-demand database snapshots, portable decrypted JSON exports,
data restoration, encryption health verification, and encryption key rotation.

Usage:
    python scripts/migrate_data.py status
    python scripts/migrate_data.py backup [--label LABEL]
    python scripts/migrate_data.py export-json [--output PATH]
    python scripts/migrate_data.py import-json --file PATH [--replace]
    python scripts/migrate_data.py restore --file PATH
    python scripts/migrate_data.py verify
    python scripts/migrate_data.py list-backups
    python scripts/migrate_data.py rotate-key [--new-key KEY]
"""

import sys
import os
import argparse
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings
from app.services.migration_service import migration_service

def cmd_status(args):
    print("\n============================================================")
    print("🔒 Obrigado - Database & Migration Status")
    print("============================================================")
    stats = migration_service.get_database_stats()
    if not stats.get("exists"):
        print("❌ Database does not exist at:", settings.db_path)
        return

    print(f"📁 Database Path:       {stats['db_path']}")
    print(f"💾 File Size:           {stats['file_size_formatted']} ({stats['file_size_bytes']:,} bytes)")
    enc_status = "✅ ACTIVE (AES-128 Fernet Envelope Encryption)" if stats["encryption_at_rest_active"] else "⚠️ NOT ACTIVE"
    print(f"🔐 Encryption at Rest:  {enc_status}")
    print(f"🛡️  Algorithm:           {stats['encryption_algorithm']}")
    print("\n📊 User Data Records:")
    counts = stats["record_counts"]
    print(f"  • Nodes / Entities:    {counts.get('nodes', 0):>5}")
    print(f"  • Knowledge Edges:     {counts.get('edges', 0):>5}")
    print(f"  • Raw Notes Captured:  {counts.get('raw_notes', 0):>5}")
    print(f"  • Daily Briefings:     {counts.get('daily_summaries', 0):>5}")
    print(f"  • Person Memories:     {counts.get('person_memories', 0):>5}")
    print(f"  • Elicitations:        {counts.get('elicitations', 0):>5}")
    print(f"  • Decision Logs:       {counts.get('decision_logs', 0):>5}")
    print(f"  • Prompts & Nudges:    {counts.get('prompts_and_nudges', 0):>5}")
    print(f"  • Token Usage Logs:    {counts.get('token_usage_logs', 0):>5}")
    print(f"  • Model Pricing Rates: {counts.get('model_pricing', 0):>5}")

    backups = migration_service.list_backups()
    print(f"\n📦 Available Backups / Snapshots: {len(backups)}")
    print("============================================================\n")

def cmd_backup(args):
    print(f"\n📦 Creating database snapshot (label: '{args.label or 'manual'}')...")
    res = migration_service.create_database_backup(args.label)
    print(f"✅ Backup created successfully!")
    print(f"  • Filename: {res['filename']}")
    print(f"  • Path:     {res['path']}")
    print(f"  • Size:     {res['file_size_formatted']}")
    print(f"  • SHA256:   {res['sha256']}")
    print(f"  • Timestamp:{res['created_at']}\n")

def cmd_export_json(args):
    print("\n📤 Exporting all user data to portable decrypted JSON...")
    res = migration_service.export_portable_json(args.output)
    print(f"✅ Portable export created successfully!")
    print(f"  • File:   {res['file_path']}")
    print(f"  • Size:   {res['size_bytes'] / 1024:.1f} KB")
    print(f"  • Counts: {res['counts']}\n")

def cmd_import_json(args):
    if not args.file:
        print("❌ Error: --file argument is required.")
        return
    print(f"\n📥 Importing user data from: {args.file}")
    if args.replace:
        print("⚠️  Warning: --replace flag set. Automatic safety backup will be created first.")
        confirm = input("Are you sure you want to replace current database content? (y/N): ")
        if confirm.lower() not in ("y", "yes"):
            print("Import cancelled.")
            return

    res = migration_service.import_portable_json(args.file, replace_existing=args.replace)
    print(f"✅ Data imported and re-encrypted successfully!")
    print(f"  • Counts: {res['imported_counts']}\n")

def cmd_restore(args):
    if not args.file:
        print("❌ Error: --file argument is required.")
        return
    print(f"\n🔄 Restoring database from snapshot: {args.file}")
    print("⚠️  A safety snapshot of the active database will be created first.")
    confirm = input("Confirm database restore? (y/N): ")
    if confirm.lower() not in ("y", "yes"):
        print("Restore cancelled.")
        return

    res = migration_service.restore_database_snapshot(args.file)
    print(f"✅ {res['message']}")
    print("============================================================\n")

def cmd_verify(args):
    print("\n🔍 Running database integrity and encryption decryption health check...")
    res = migration_service.verify_database_integrity()
    if res["healthy"]:
        print("✅ DATABASE INTEGRITY & ENCRYPTION HEALTH: 100% HEALTHY")
        print(f"  • SQLite PRAGMA Integrity: {res['sqlite_integrity']}")
        print(f"  • Encrypted Fields Tested: {res['total_records_checked']}")
        print(f"  • Decryption Failures:     0")
        print(f"  • Health Score:            {res['decryption_health_pct']}%")
    else:
        print("❌ INTEGRITY WARNINGS DETECTED:")
        print(f"  • SQLite PRAGMA Integrity: {res['sqlite_integrity']}")
        print(f"  • Decryption Errors:       {res['decryption_errors_count']}")
        for err in res["decryption_errors"]:
            print(f"    - {err}")
    print("============================================================\n")

def cmd_list_backups(args):
    backups = migration_service.list_backups()
    print("\n==========================================================================================")
    print(f"📦 Obrigado Backups & Snapshots ({len(backups)} total)")
    print("==========================================================================================")
    print(f"{'Filename':<46} {'Type':<16} {'Size':<10} {'Created / Modified'}")
    print("-" * 90)
    for b in backups:
        btype = "Baseline Backup" if b.get("is_baseline") else ("SQLite DB" if b["file_type"] == "sqlite_backup" else "JSON Export")
        print(f"{b['filename']:<46} {btype:<16} {b['size_formatted']:<10} {b['modified_at']}")
    print("==========================================================================================\n")

def cmd_rotate_key(args):
    print("\n🔑 Initiating master encryption key rotation...")
    print("⚠️  A full database backup will be created automatically before key rotation.")
    confirm = input("Confirm master key rotation? (y/N): ")
    if confirm.lower() not in ("y", "yes"):
        print("Key rotation cancelled.")
        return

    res = migration_service.rotate_encryption_key(args.new_key)
    print(f"✅ {res['message']}")
    print(f"  • Re-encrypted records: {res['re_encrypted_counts']}\n")

def main():
    parser = argparse.ArgumentParser(
        description="Obrigado Migration & Backup CLI Utility",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # status
    subparsers.add_parser("status", help="Show database record counts, encryption, and backup status")

    # backup
    p_backup = subparsers.add_parser("backup", help="Create an atomic SQLite database backup snapshot")
    p_backup.add_argument("--label", type=str, default="", help="Optional label to append to filename")

    # export-json
    p_exp = subparsers.add_parser("export-json", help="Export all user data to portable decrypted JSON")
    p_exp.add_argument("--output", "-o", type=str, default=None, help="Custom output file path")

    # import-json
    p_imp = subparsers.add_parser("import-json", help="Import user data from a portable JSON export file")
    p_imp.add_argument("--file", "-f", type=str, required=True, help="Path to JSON export file")
    p_imp.add_argument("--replace", action="store_true", help="Replace existing records instead of merging")

    # restore
    p_res = subparsers.add_parser("restore", help="Restore database from a SQLite snapshot file")
    p_res.add_argument("--file", "-f", type=str, required=True, help="Path or filename of SQLite backup")

    # verify
    subparsers.add_parser("verify", help="Verify SQLite integrity and decrypt all records to test health")

    # list-backups
    subparsers.add_parser("list-backups", help="List all available database snapshots and JSON backups")

    # rotate-key
    p_rot = subparsers.add_parser("rotate-key", help="Rotate master encryption key and re-encrypt all records")
    p_rot.add_argument("--new-key", type=str, default=None, help="Optional base64 32-byte Fernet key string")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    cmds = {
        "status": cmd_status,
        "backup": cmd_backup,
        "export-json": cmd_export_json,
        "import-json": cmd_import_json,
        "restore": cmd_restore,
        "verify": cmd_verify,
        "list-backups": cmd_list_backups,
        "rotate-key": cmd_rotate_key,
    }

    cmd_fn = cmds.get(args.command)
    if cmd_fn:
        cmd_fn(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
