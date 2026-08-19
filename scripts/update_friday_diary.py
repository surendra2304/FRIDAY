#!/usr/bin/env python3
import os
import re
from datetime import datetime
import sys

def main():
    today = datetime.now().strftime('%Y-%m-%d')
    diary_file = f"diary/{today}.md"
    
    if not os.path.exists('diary'):
        os.makedirs('diary')
        
    if not os.path.exists(diary_file):
        with open(diary_file, 'w', encoding='utf-8') as f:
            f.write(f"# FRIDAY — {today}\n\n")
            f.write("## Daily Summary\n\n")
            f.write("## User Directives / Requirements\n\n")
            f.write("## Work Performed\n\n")
            f.write("## Architecture / Structure Changes\n\n")
            f.write("## Files Created\n\n")
            f.write("## Files Modified\n\n")
            f.write("## Files Deleted\n\n")
            f.write("## Gemini / LLM Changes\n\n")
            f.write("## Voice / Live API Changes\n\n")
            f.write("## Memory / Embeddings Changes\n\n")
            f.write("## Tools / Agent Changes\n\n")
            f.write("## Security Changes\n\n")
            f.write("## CLI / UI Changes\n\n")
            f.write("## Tests Performed & Test Results\n\n")
            f.write("## Bugs / Errors Discovered\n\n")
            f.write("## Important Decisions\n\n")
            f.write("## Incidents / Misconfigurations\n\n")
            f.write("## Corrections to Earlier Information\n\n")
            f.write("## Git Commits\n\n")
            f.write("## API / Cloud Events\n\n")
            f.write("## Current End-of-Day State\n\n")
            f.write("## Next Planned Work\n\n")
        print(f"Created {diary_file}")
    else:
        print(f"Diary for today ({today}) already exists.")

    # Update master FRIDAY_DIARY.md navigation if missing
    if os.path.exists('FRIDAY_DIARY.md'):
        with open('FRIDAY_DIARY.md', 'r', encoding='utf-8') as f:
            content = f.read()
            
        nav_entry = f"- [{today}](diary/{today}.md)"
        if nav_entry not in content:
            # Insert nav entry at the end of Diary Navigation
            content = re.sub(
                r'(## Diary Navigation\n\nA chronological list:\n\n[\s\S]*?)(?=\n---)',
                lambda m: m.group(1).rstrip() + f"\n{nav_entry}\n\n",
                content
            )
            with open('FRIDAY_DIARY.md', 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"Added {today} to FRIDAY_DIARY.md navigation.")
            
    print("\nRemember to never commit secrets or .env variables to the diary.")

if __name__ == '__main__':
    main()
