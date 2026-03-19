import logging
import os
from src.db import get_latest_digest

logger = logging.getLogger(__name__)

def generate_report(new_summaries, grouped_messages, groups_list, db_path):
    """
    Generates the final report text by combining new summaries and cached ones.
    """
    print("\n" + "="*60)
    print("TELEGRAM DIGEST OUTPUT")
    print("="*60 + "\n")
    
    digest_output = "TELEGRAM DIGEST OUTPUT\n" + "="*40 + "\n\n"
    printed_groups = set()
    
    # 1. New Content First
    for gid, group_info in grouped_messages.items():
        gname = group_info["name"]
        idx = list(grouped_messages.keys()).index(gid)
        summary_text = new_summaries[idx]
        
        print(summary_text)
        print("-" * 40)
        digest_output += summary_text + "\n" + "-"*40 + "\n"
        
        printed_groups.add(gid)
        printed_groups.add(gname)
        
    # 2. Cached Content for any other targets
    for target in groups_list:
        if target in printed_groups: continue
        
        cached_digest = get_latest_digest(db_path, target)
        if cached_digest:
            cached_text = f"[CACHED DIGEST - NO NEW MESSAGES]\n{cached_digest}"
            print(cached_text)
            print("-" * 40)
            digest_output += cached_text + "\n" + "-"*40 + "\n"
            printed_groups.add(target)
            
    if not printed_groups:
        no_msg = "### Summary\n\n*No messages found and no previous digests exist.*\n"
        print(no_msg)
        print("-" * 40)
        digest_output += no_msg + "-"*40 + "\n"
        
    return digest_output

def save_and_print_metadata(digest_output, all_messages, hours_back, api_duration, output_file):
    """
    Appends metadata, prints it, and saves the final content to the output file.
    """
    if all_messages:
        dates = [m['date'] for m in all_messages]
        time_range = f"{min(dates)} to {max(dates)}"
    else:
        time_range = "N/A"

    metadata = f"\n[METADATA]\n- Time Range: {time_range}\n- Config Window: last {hours_back} hours\n- Total messages processed: {len(all_messages)}\n- API Processing Time: {api_duration:.2f}s\n"
    print(metadata)
    
    final_content = digest_output + metadata
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(final_content)
    
    logger.info(f"Latest digest saved to {output_file}")
    return metadata
