#!/bin/bash

# Run from the folder containing your MP4s, just like the original script.
# Compatible with the Bash 3.2 shipped with macOS; no extra UI dependencies.
shopt -s nullglob
videos=(*.mp4)
total=${#videos[@]}
converted=0 skipped=0 failed=0 completed=0
started=$SECONDS
work_dir=''
encoder_pid='' logger_pid='' progress_pid=''
bold='' dim='' cyan='' green='' yellow='' red='' reset=''
interactive=false
if [ -t 1 ] && [ "${TERM:-dumb}" != dumb ]; then
    interactive=true
    if [ -z "${NO_COLOR+x}" ]; then
        bold=$'\033[1m' dim=$'\033[2m' cyan=$'\033[36m'
        green=$'\033[32m' yellow=$'\033[33m' red=$'\033[31m' reset=$'\033[0m'
    fi
fi

rule() { printf '\n%s------------------------------------------------------------%s\n' "$dim" "$reset"; }

bar() {
    local percent=$1 width=24 filled empty
    filled=$((percent * width / 100))
    empty=$((width - filled))
    printf '['
    printf '%*s' "$filled" '' | tr ' ' '#'
    printf '%*s' "$empty" '' | tr ' ' '-'
    printf '] %3d%%' "$percent"
}

batch_progress() {
    printf '  %sBatch: %d/%d files handled%s\n' "$dim" "$completed" "$total" "$reset"
}

cleanup() {
    stop_workers
    # Only our temporary encoding files are removed, never existing videos.
    if [ -n "$work_dir" ]; then rm -rf -- "$work_dir"; fi
}

stop_workers() {
    local pid
    for pid in "$encoder_pid" "$logger_pid" "$progress_pid"; do
        if [ -n "$pid" ]; then kill -TERM "$pid" 2>/dev/null || :; fi
    done
    for pid in "$encoder_pid" "$logger_pid" "$progress_pid"; do
        if [ -n "$pid" ]; then wait "$pid" 2>/dev/null || :; fi
    done
    encoder_pid='' logger_pid='' progress_pid=''
}

interrupted() {
    trap '' INT TERM
    stop_workers
    printf '\n\n%s🛑 STOPPED — entire batch canceled.%s\n' "$yellow" "$reset"
    printf '   Completed videos are safe; no further files will be started.\n'
    exit 130
}
trap cleanup EXIT
trap interrupted INT TERM

# HandBrake uses both carriage returns and newlines. Read either immediately,
# without a buffered filter delaying the progress display. Full output is logged.
show_progress() {
    local char line='' pattern='^Encoding:.*,[[:space:]]*([0-9]+)[.]([0-9]+)[[:space:]]*%' percent last=-1
    while IFS= read -r -n 1 char; do
        if [ -z "$char" ] || [ "$char" = $'\r' ]; then
            if [[ "$line" =~ $pattern ]]; then
                percent=${BASH_REMATCH[1]}
                percent=$((10#$percent))
                [ "$percent" -gt 100 ] && percent=100
                if [ "$percent" -ne "$last" ]; then
                    if $interactive; then
                        printf '\r\033[2K  %sEncoding%s  ' "$cyan" "$reset"
                        bar "$percent"
                    elif [ "$last" -lt 0 ] || [ "$percent" -eq 100 ] || [ "$((percent / 10))" -ne "$((last / 10))" ]; then
                        printf '  Encoding  '
                        bar "$percent"
                        printf '\n'
                    fi
                    last=$percent
                fi
            fi
            line=''
        else
            line+=$char
        fi
    done
    if $interactive && [ "$last" -ge 0 ]; then printf '\n'; fi
}

rule
printf '%s📺  XIAOMI TV CONVERTER%s\n' "$bold$cyan" "$reset"
printf '  Source:       %s\n' "$PWD"
printf '  Destination:  %s/xiaomitv\n' "$PWD"
printf '  Preset:       Fast 1080p30\n'
printf '  Queue:        %s%d MP4 file(s)%s\n' "$bold" "$total" "$reset"
printf '  Existing destination filenames will be skipped.\n'
printf '  Ctrl-C stops the entire batch.\n'
printf '\n'

if [ "$total" -eq 0 ]; then
    printf '\n%s📭  No MP4 files found in this folder.%s\n\n' "$yellow" "$reset"
    exit 0
fi
if ! mkdir -p xiaomitv; then
    printf '\n%s❌ Cannot create the destination folder.%s\n' "$red" "$reset" >&2
    exit 1
fi

for video in "${videos[@]}"; do
    base=${video%.mp4}
    output="xiaomitv/${base}.mp4"
    if [ -f "$output" ]; then
        skipped=$((skipped + 1))
        completed=$((completed + 1))
        printf '  %s⏭️  Skipped: %s (already in xiaomitv) · %d/%d files handled%s\n' \
            "$dim" "$video" "$completed" "$total" "$reset"
        continue
    else
        rule
        printf '%s[%d / %d]  %s%s\n\n' "$bold" "$((completed + 1))" "$total" "$video" "$reset"
        printf '  %s🎬 CONVERTING%s\n' "$cyan$bold" "$reset"
        printf '  From:  %s\n' "$video"
        printf '  To:    %s\n' "$output"
        subtitle_args=()
        if [ -f "${base}.srt" ]; then
            printf '  💬 Subtitles: %s.srt\n' "$base"
            subtitle_args=(--srt-file "${base}.srt" --subtitle-burned=none --srt-codeset UTF-8)
        else
            printf '  💬 Subtitles: none found\n'
        fi

        if ! command -v HandBrakeCLI >/dev/null 2>&1; then
            printf '\n%s❌ HandBrakeCLI was not found on PATH.%s\n' "$red" "$reset" >&2
            exit 1
        fi
        # An interrupted/failed encode must not become a matching filename
        # that would incorrectly be skipped on the next run.
        work_dir=$(mktemp -d xiaomitv/.xm-convert.XXXXXX) || exit 1
        log_file=$(mktemp "${TMPDIR:-/tmp}/xm-convert.XXXXXX") || exit 1
        mkfifo "$work_dir/encoder-output" "$work_dir/progress-output" || exit 1
        printf '\n  Starting HandBrake… progress will appear when encoding begins.\n'
        file_started=$SECONDS
        # Wait on explicit background children so Bash can handle Ctrl-C
        # immediately, instead of deferring its trap behind a foreground pipeline.
        show_progress < "$work_dir/progress-output" &
        progress_pid=$!
        tee "$log_file" < "$work_dir/encoder-output" > "$work_dir/progress-output" &
        logger_pid=$!
        HandBrakeCLI -i "$video" -o "$work_dir/video.mp4" \
            -Z "Fast 1080p30" "${subtitle_args[@]}" </dev/null > "$work_dir/encoder-output" 2>&1 &
        encoder_pid=$!
        wait "$encoder_pid"
        result=$?
        encoder_pid=''
        # Also stop if the encoder itself was terminated by a signal.
        case "$result" in 130|143) interrupted ;; esac
        wait "$logger_pid"
        logger_pid=''
        wait "$progress_pid"
        progress_pid=''
        if [ "$result" -eq 0 ] && [ -s "$work_dir/video.mp4" ] && mv -n "$work_dir/video.mp4" "$output" && [ ! -e "$work_dir/video.mp4" ]; then
            printf '  %sComplete%s  ' "$green" "$reset"
            bar 100
            printf '\n'
            printf '\n  %s✅ CONVERTED%s in %dm %02ds\n' "$green$bold" "$reset" \
                "$(((SECONDS - file_started) / 60))" "$(((SECONDS - file_started) % 60))"
            printf '  Saved: %s\n' "$output"
            converted=$((converted + 1))
            rm -f -- "$log_file"
        else
            printf '  %s❌ Failed: %s%s (HandBrake exit %s; output not saved)\n' "$red" "$video" "$reset" "$result"
            printf '  %sDetails: %s%s\n' "$dim" "$log_file" "$reset"
            failed=$((failed + 1))
        fi
        cleanup
        work_dir=''
    fi
    completed=$((completed + 1))
    batch_progress
done

rule
if [ "$failed" -gt 0 ]; then
    printf '%s⚠️  FINISHED WITH ERRORS%s\n' "$yellow$bold" "$reset"
else
    printf '%s🏁  ALL FILES CHECKED%s\n' "$green$bold" "$reset"
fi
printf '\n  %s✅ Converted: %d%s\n  %s⏭️  Skipped:   %d%s (matching destination filenames)\n  %s❌ Failed:    %d%s\n' \
    "$green" "$converted" "$reset" "$yellow" "$skipped" "$reset" "$red" "$failed" "$reset"
printf '\n  Time:    %dm %02ds\n' "$(((SECONDS - started) / 60))" "$(((SECONDS - started) % 60))"
printf '  Output:  %s/xiaomitv\n\n' "$PWD"
[ "$failed" -eq 0 ]
