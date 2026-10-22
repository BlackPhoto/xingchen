# Restore Workflow

This workflow is mandatory whenever the user explicitly asks to restore, roll back, undo, or revert a previously accepted Skill evolution.

## Mandatory boundary

Before responding to the Restore request or calling `skill_evolution_resolve`, read this document in full.

Never reconstruct this workflow from memory. Never improvise an alternative Restore flow. Never call `skill_evolution_resolve` with `action="restore"` before reading this document.

## 1. Identify the Skill and receipt

Determine the target Skill from the user's request. Look for the exact rollback receipt in the current conversation context. The receipt is shown after a successful Accept.

If the receipt is absent, do not call the tool. Ask the user:

> 我在当前上下文中找不到这次变更的回退凭证。请从当时“已接受变更”的消息中复制凭证给我。

Never guess, construct, alter, or substitute a receipt.

## 2. Execute the first Restore attempt

When both the Skill name and exact receipt are known, call `skill_evolution_resolve` with:

- `action="restore"`
- `skillName="<skillName>"`
- `receipt="<exact receipt>"`
- omit `replaceExisting`, or set it to `false`

The tool checks the current single backup and immediately restores when the request is unambiguous. Do not ask for an extra confirmation before this first call: the user's explicit Restore request is the authorization.

## 3. Unavailable Restore

If the tool returns `restored=false`, report its exact reason and state that no Skill was modified.

For `receipt_mismatch`, show `currentBackupCreatedAt` when present and explain that a later backup has replaced the requested rollback opportunity. Never offer to restore the current backup instead. Never retry with another receipt.

For `legacy_backup_unsupported`, explain that the backup predates rollback receipts and cannot be matched safely.

For `live_skill_missing`, explain that the current formal Skill is absent and a patch rollback cannot be applied safely.

## 4. Delete Restore conflict

If the tool returns `reason="live_skill_conflict"`, the deleted Skill's old name is currently occupied by another formal Skill. The first call has not changed any files.

Present exactly two choices:

1. Replace the current same-name Skill and restore the backup.
2. Cancel the Restore.

Clearly warn that replacement permanently discards all content in the current same-name Skill.

If the user explicitly chooses replacement, call the same tool again with the same `skillName` and `receipt`, plus `replaceExisting=true`.

If the user cancels or gives an ambiguous response, do not call the tool again. Never set `replaceExisting=true` on the first Restore attempt or without explicit approval after `live_skill_conflict`.

## 5. Successful Restore

Report the `operation` returned by the tool.

When a successful Restore returns `requiresExternalRegistration=true`, register the restored Skill before reporting success by running:

```bash
python scripts/add_skill_remote.py <registrationPath>
```

Use the exact absolute `registrationPath` returned by the tool. The script applies the same permission and 100-Skill limit check used by every registration, but always sends the registration request. If it returns `{"ok": true, "reason": "registered_denied"}`, state that the files were restored and registered but the Skill remains disabled because the limit has been reached. If registration fails, state that the files were restored but runtime registration failed; do not claim the Skill is enabled.

- `patch`: state that the Skill was restored from the backup and later formal-Skill modifications were overwritten.
- `create`: state that the Skill created by the accepted evolution was removed. If `alreadyAbsent=true`, state that it was already absent and the receipt was consumed.
- `delete`: state that the deleted Skill was restored. If `replacedExisting=true`, also state that the conflicting same-name Skill was replaced as explicitly authorized.

The single backup is consumed after a successful Restore. Do not claim that the same receipt or older versions remain recoverable.
