from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

@dataclass
class ParquetWriteConfig:
    root_dir: Path
    existing_data_behavior: str = "delete_matching"  # "overwrite" or "append"
    
def write_partitioned_parquet(
    df: pd.DataFrame, 
    cfg: ParquetWriteConfig, 
    partition_cols: List[str]
    ) -> None:
    """Writes a DataFrame to partitioned Parquet files on disk.
    
    Partitions the data by the specified columns, creating subdirectories for each unique value.
    Handles existing data according to the specified behavior (overwrite or append).
    """
    # Convert DataFrame to PyArrow Table
    if df.empty:
        print("Warning: DataFrame is empty. No Parquet files will be written.")
        return
    
    cfg.root_dir.mkdir(parents=True, exist_ok=True)
    
    table = pa.Table.from_pandas(
        df,
        preserve_index=False,
        )
    
    # Write partitioned Parquet files
    pq.write_to_dataset(
        table,
        root_path=str(cfg.root_dir),
        partition_cols=partition_cols,
        existing_data_behavior=cfg.existing_data_behavior,
    )