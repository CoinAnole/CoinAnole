#!/usr/bin/env bash
# commit_to_master.sh - Commit and push changes directly to master using gh CLI
# This script intentionally updates only master (CodePet requirement).
#
# Usage: ./commit_to_master.sh "Commit message" [file1] [file2] ...
# If no file args are provided, it commits all working-tree changes.

set -euo pipefail

COMMIT_MESSAGE="${1:-Update from cloud agent}"
if [ $# -gt 0 ]; then
    shift
fi

TEMP_FILES=()
cleanup() {
    local file
    for file in "${TEMP_FILES[@]}"; do
        [ -n "$file" ] && [ -e "$file" ] && rm -f "$file"
    done
}
trap cleanup EXIT

die() {
    echo "Error: $*" >&2
    exit 1
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

json_escape() {
    local raw="$1"
    raw=${raw//\\/\\\\}
    raw=${raw//\"/\\\"}
    raw=${raw//$'\n'/\\n}
    raw=${raw//$'\r'/\\r}
    raw=${raw//$'\t'/\\t}
    printf '%s' "$raw"
}

base64_no_wrap() {
    local file="$1"
    if base64 --help 2>/dev/null | grep -q -- '-w'; then
        base64 -w 0 "$file"
    else
        base64 "$file" | tr -d '\n'
    fi
}

resolve_repo() {
    local remote_url repo_from_gh owner name

    if [ -n "${GITHUB_REPOSITORY:-}" ] && [[ "${GITHUB_REPOSITORY}" == */* ]]; then
        printf '%s' "${GITHUB_REPOSITORY}"
        return 0
    fi

    if [ -n "${GITHUB_REPOSITORY_OWNER:-}" ] && [ -n "${GITHUB_REPOSITORY_NAME:-}" ]; then
        printf '%s/%s' "${GITHUB_REPOSITORY_OWNER}" "${GITHUB_REPOSITORY_NAME}"
        return 0
    fi

    remote_url=$(git remote get-url origin 2>/dev/null || true)
    if [[ "$remote_url" =~ github\.com[:/]([^/]+)/([^/]+)$ ]]; then
        owner="${BASH_REMATCH[1]}"
        name="${BASH_REMATCH[2]}"
        name="${name%.git}"
        printf '%s/%s' "$owner" "$name"
        return 0
    fi

    repo_from_gh=$(gh repo view --json nameWithOwner --jq '.nameWithOwner' 2>/dev/null || true)
    if [ -n "$repo_from_gh" ]; then
        printf '%s' "$repo_from_gh"
        return 0
    fi

    return 1
}

get_file_mode() {
    local file="$1"
    if [ -L "$file" ]; then
        printf '120000'
    elif [ -x "$file" ]; then
        printf '100755'
    else
        printf '100644'
    fi
}

create_blob_sha() {
    local file="$1"
    local blob_payload blob_sha content

    blob_payload=$(mktemp)
    TEMP_FILES+=("$blob_payload")

    if [ -L "$file" ]; then
        content=$(printf '%s' "$(readlink "$file")" | base64 | tr -d '\n')
    else
        content=$(base64_no_wrap "$file")
    fi

    printf '{"encoding":"base64","content":"%s"}' "$content" >"$blob_payload"
    blob_sha=$(gh api "repos/$REPO/git/blobs" --input "$blob_payload" --jq '.sha')
    printf '%s' "$blob_sha"
}

collect_files_from_git_status() {
    local entry status x y old_path new_path

    while IFS= read -r -d '' entry; do
        status="${entry:0:2}"
        x="${status:0:1}"
        y="${status:1:1}"
        old_path="${entry:3}"

        if [[ "$status" == "!!" ]]; then
            continue
        fi

        if [[ "$x" == "R" || "$y" == "R" || "$x" == "C" || "$y" == "C" ]]; then
            IFS= read -r -d '' new_path || new_path=""
            if [[ "$x" == "R" || "$y" == "R" ]]; then
                DELETED_PATHS["$old_path"]=1
                unset "LIVE_PATHS[$old_path]"
            fi
            if [ -n "$new_path" ]; then
                if [ -e "$new_path" ] || [ -L "$new_path" ]; then
                    LIVE_PATHS["$new_path"]=1
                    unset "DELETED_PATHS[$new_path]"
                else
                    DELETED_PATHS["$new_path"]=1
                    unset "LIVE_PATHS[$new_path]"
                fi
            fi
            continue
        fi

        if [[ "$x" == "D" || "$y" == "D" ]]; then
            DELETED_PATHS["$old_path"]=1
            unset "LIVE_PATHS[$old_path]"
            continue
        fi

        if [[ "$status" == "??" || "$x" != " " || "$y" != " " ]]; then
            if [ -e "$old_path" ] || [ -L "$old_path" ]; then
                LIVE_PATHS["$old_path"]=1
                unset "DELETED_PATHS[$old_path]"
            else
                DELETED_PATHS["$old_path"]=1
                unset "LIVE_PATHS[$old_path]"
            fi
        fi
    done < <(git status --porcelain=1 -z)
}

require_cmd gh
require_cmd git
require_cmd base64

if ! REPO=$(resolve_repo); then
    die "Could not determine repository. Set GITHUB_REPOSITORY=owner/repo."
fi

echo "Targeting repository: $REPO"
echo "Branch: master"

declare -A LIVE_PATHS=()
declare -A DELETED_PATHS=()

if [ $# -gt 0 ]; then
    for path in "$@"; do
        if [ -e "$path" ] || [ -L "$path" ]; then
            LIVE_PATHS["$path"]=1
            unset "DELETED_PATHS[$path]"
        else
            DELETED_PATHS["$path"]=1
            unset "LIVE_PATHS[$path]"
        fi
    done
else
    collect_files_from_git_status
fi

FILES_TO_COMMIT=("${!LIVE_PATHS[@]}")
FILES_TO_DELETE=("${!DELETED_PATHS[@]}")

if [ ${#FILES_TO_COMMIT[@]} -eq 0 ] && [ ${#FILES_TO_DELETE[@]} -eq 0 ]; then
    echo "No files to commit"
    exit 0
fi

echo "Files to add/update (${#FILES_TO_COMMIT[@]}):"
for file in "${FILES_TO_COMMIT[@]}"; do
    echo "  $file"
done
echo "Files to delete (${#FILES_TO_DELETE[@]}):"
for file in "${FILES_TO_DELETE[@]}"; do
    echo "  $file"
done

TREE_ITEMS=()
for file in "${FILES_TO_COMMIT[@]}"; do
    [ -e "$file" ] || [ -L "$file" ] || continue
    mode="$(get_file_mode "$file")"
    blob_sha="$(create_blob_sha "$file")"
    echo "Created blob for $file: $blob_sha"
    TREE_ITEMS+=("{\"path\":\"$(json_escape "$file")\",\"mode\":\"$mode\",\"type\":\"blob\",\"sha\":\"$blob_sha\"}")
done

for file in "${FILES_TO_DELETE[@]}"; do
    echo "Marked for deletion: $file"
    TREE_ITEMS+=("{\"path\":\"$(json_escape "$file")\",\"mode\":\"100644\",\"type\":\"blob\",\"sha\":null}")
done

if [ ${#TREE_ITEMS[@]} -eq 0 ]; then
    echo "No valid file operations to commit"
    exit 0
fi

IFS=,
TREE_ITEMS_JSON="${TREE_ITEMS[*]}"
unset IFS

MAX_RETRIES=3
attempt=1

while [ "$attempt" -le "$MAX_RETRIES" ]; do
    echo "Commit attempt $attempt/$MAX_RETRIES..."
    MASTER_SHA=$(gh api "repos/$REPO/git/refs/heads/master" --jq '.object.sha')
    BASE_TREE_SHA=$(gh api "repos/$REPO/git/commits/$MASTER_SHA" --jq '.tree.sha')
    echo "Current master SHA: $MASTER_SHA"

    tree_payload=$(mktemp)
    TEMP_FILES+=("$tree_payload")
    printf '{"base_tree":"%s","tree":[%s]}' "$BASE_TREE_SHA" "$TREE_ITEMS_JSON" >"$tree_payload"
    NEW_TREE_SHA=$(gh api "repos/$REPO/git/trees" --input "$tree_payload" --jq '.sha')
    echo "Created tree: $NEW_TREE_SHA"

    commit_payload=$(mktemp)
    TEMP_FILES+=("$commit_payload")
    printf '{"message":"%s","tree":"%s","parents":["%s"]}' \
        "$(json_escape "$COMMIT_MESSAGE")" \
        "$NEW_TREE_SHA" \
        "$MASTER_SHA" >"$commit_payload"
    NEW_COMMIT_SHA=$(gh api "repos/$REPO/git/commits" --input "$commit_payload" --jq '.sha')
    echo "Created commit: $NEW_COMMIT_SHA"

    ref_error=$(mktemp)
    TEMP_FILES+=("$ref_error")
    if gh api "repos/$REPO/git/refs/heads/master" -X PATCH -f sha="$NEW_COMMIT_SHA" -F force=false \
        >/dev/null 2>"$ref_error"; then
        echo "Successfully pushed to master!"
        echo "Commit URL: https://github.com/$REPO/commit/$NEW_COMMIT_SHA"
        exit 0
    fi

    echo "Failed to update master reference on attempt $attempt:" >&2
    cat "$ref_error" >&2

    if [ "$attempt" -lt "$MAX_RETRIES" ]; then
        sleep "$attempt"
    fi
    attempt=$((attempt + 1))
done

die "Unable to update master after $MAX_RETRIES attempts."
