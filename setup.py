import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="mdb_cmdline_tool",
    version="1.0.0-alpha1",
    author="Robert Guo",
    author_email="rob@mongodb.com",
    description="MongoDB Server Team Command Line Tool",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/10gen/kernel-tools/cmdlinetool",
    packages=setuptools.find_packages(),
    classifiers=(
        "Development Status :: 3 - Alpha",
        "Programming Language :: Python :: 3 :: Only",
        "License "" Other/Proprietary License",
        "Operating System :: MacOS :: MacOS X",
    ),
)