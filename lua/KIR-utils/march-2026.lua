whatis("Helper scripts")

add_property("lmod", "sticky")

local root = "/apps/kir/eb/hpc-utils"

prepend_path("PATH", root)
setenv("UV_CACHE_DIR", pathJoin(root, ".uv-cache"))
