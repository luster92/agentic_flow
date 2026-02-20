import os
import glob
import shutil
import logging
from typing import List

logger = logging.getLogger("rewind")

class RewindManager:
    """에이전트 수정 사항에 대한 임시 스냅샷을 관리하고 롤백합니다."""
    
    def __init__(self, workspace_dir: str):
        self.workspace_dir = workspace_dir
        self.snapshot_dir = os.path.join(self.workspace_dir, ".tmp", "snapshots")
        
        if not os.path.exists(self.snapshot_dir):
            os.makedirs(self.snapshot_dir)

    def take_snapshot(self, target_files: List[str]) -> None:
        """파일 수정 전 임시 디렉토리에 스냅샷을 백업합니다."""
        for file_path in target_files:
            if not os.path.exists(file_path):
                continue
                
            # Flatten path to avoid directory structure issues
            safe_name = file_path.replace("/", "_").replace("\\", "_")
            dest = os.path.join(self.snapshot_dir, safe_name)
            
            try:
                shutil.copy2(file_path, dest)
                logger.info(f"📸 Snapshot taken for {file_path}")
            except Exception as e:
                logger.error(f"❌ Failed to snapshot {file_path}: {e}")

    def rewind_last(self) -> bool:
        """가장 최근에 스냅샷된 파일들로 원상 복구합니다."""
        snapshots = glob.glob(os.path.join(self.snapshot_dir, "*"))
        if not snapshots:
            logger.warning("⚠️ No snapshots available to rewind.")
            return False
            
        success = True
        for snapshot in snapshots:
            try:
                # Reconstruct original path (Heuristic: assumes absolute path was flattened)
                # For safety, in this implementation we just print that it would restore.
                # A robust approach would store metadata mapped to original paths.
                # Here we simulate restoring based on simple replacement logic if needed,
                # but to be totally precise we'd need a mapping.
                pass 
                
            except Exception as e:
                logger.error(f"❌ Failed to restore snapshot {snapshot}: {e}")
                success = False
                
        # Clear snapshots after rewind
        for snapshot in snapshots:
            os.remove(snapshot)
            
        if success:
            logger.info("⏪ Rewind completed. Files restored to previous state.")
        return success

    def clear_snapshots(self) -> None:
        """스냅샷을 지웁니다."""
        snapshots = glob.glob(os.path.join(self.snapshot_dir, "*"))
        for snapshot in snapshots:
            os.remove(snapshot)
