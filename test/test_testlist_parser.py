from pathlib import Path

from testlist_parser import load_jobs

REGRESS_YAML = Path(__file__).resolve().parent / "regress.yaml"


def test_load_jobs_merges_global_and_entry_run_args():
    jobs = load_jobs(REGRESS_YAML)
    by_name = {job.name: job for job in jobs}

    alpine = by_name["alpine_regbuild"]
    assert alpine.run_args == [
        "AUTO", "-r", "-p", "rv64_qh_regbuild", "-c", "cmd_files/bbl"
    ]
    assert alpine.run_program == "runEmu.py"
    assert alpine.setup_args == ["EXTRACT", "-r"]

    voxel1 = by_name["voxel_release_sim00_regbuild_1"]
    voxel2 = by_name["voxel_release_sim00_regbuild_2"]
    assert voxel1.run_args == [
        "AUTO", "-r", "-p", "VOXEL/sowph1A_rel3", "-c", "cmd_files/voxel_sowph",
        "--extdata", "VOXEL/sowph1A_rel3/extdata.128b.hex",
        "--sram", "VOXEL/sowph1A_rel3/sram_bXX.hex",
    ]
    assert voxel2.run_args == [
        "AUTO", "-r", "-p", "VOXEL/sowph1B_rel1", "-c", "cmd_files/voxel_sowph",
        "--extdata", "VOXEL/sowph1A_rel3/extdata.128b.hex",
        "--sram", "VOXEL/sowph1B_rel1/sram_bXX.hex",
    ]
    assert voxel1.domains == 8
    assert voxel2.domains == 8
