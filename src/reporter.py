import logging
import os
from src.db import get_latest_digest

logger = logging.getLogger(__name__)

def build_report(
    new_summaries: list[str], 
    grouped_messages: dict, 
    groups_list: list[str], 
    db_path: str
) -> str:
    """
    Pure function: Generates the final report text by combining new summaries and cached ones.
    No print statements or side effects.
    """
    digest_output = "TELEGRAM DIGEST OUTPUT\n" + "="*40 + "\n\n"
    printed_groups = set()
    
    # 1. New Content First
    for gid, group_info in grouped_messages.items():
        summary_text = new_summaries[list(grouped_messages.keys()).index(gid)]
        digest_output += summary_text + "\n" + "-"*40 + "\n"
        printed_groups.add(gid)
        printed_groups.add(group_info["name"])
        
    # 2. Cached Content for any other targets
    for target in groups_list:
        if target in printed_groups: continue
        
        cached_digest = get_latest_digest(db_path, target)
        if cached_digest:
            cached_text = f"[CACHED DIGEST - NO NEW MESSAGES]\n{cached_digest}"
            digest_output += cached_text + "\n" + "-"*40 + "\n"
            printed_groups.add(target)
            
    if not printed_groups:
        no_msg = "### Summary\n\n*No messages found and no previous digests exist.*\n"
        digest_output += no_msg + "-"*40 + "\n"
        
    return digest_output

def finalize_report(
    digest_output: str, 
    all_messages: list[dict], 
    hours_back: int, 
    api_duration: float, 
    output_file: str
) -> None:
    """
    Side effects only: Compiles metadata, prints to stdout, and saves to file.
    """
    if all_messages:
        dates = [m['date'] for m in all_messages]
        time_range = f"{min(dates)} to {max(dates)}"
    else:
        time_range = "N/A"

    metadata = (
        f"\n[METADATA]\n"
        f"- Time Range: {time_range}\n"
        f"- Config Window: last {hours_back} hours\n"
        f"- Total messages processed: {len(all_messages)}\n"
        f"- API Processing Time: {api_duration:.2f}s\n"
    )
    
    final_content = digest_output + metadata
    
    # 1. Print to console
    print("\n" + "="*60)
    print(final_content)
    print("="*60 + "\n")
    
    # 2. Save to file
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(final_content)
    
    logger.info(f"Report saved to {output_file}")
