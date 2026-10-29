Place the official **Linux** AmazingData and tgw `.whl` files here, with any
vendor-supplied dependency wheels. Choose the matching server CPU architecture
and Python version (the default image uses Python 3.12). Keep only one version
of each package. Wheels are ignored by Git but included by the existing rsync.

The manual lists the official download page:
https://cloud.chinastock.com.cn/p/DSG36jYQx2IY_Y8CIAA

If the installed SDK needs additional native libraries or a different Linux
base, use the vendor's supported runtime and update Dockerfile.
The build checks SDK import and dependency consistency before producing an image.
