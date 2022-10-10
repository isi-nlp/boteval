#!/usr/bin/env bash
# Author: Thamme Gowda
# Created: Oct 2022

# this build file is influenced by https://github.com/isi-nlp/rtg/blob/master/docs/make-docs.sh 
# 
DOCS_DIR="$(dirname "${BASH_SOURCE[0]}")"  # Get the directory name
DOCS_DIR="$(realpath "${DOCS_DIR}")"            # Resolve its full path if need be
PACKAGE='boteval'

function my_exit {
  # my_exit <exit-code> <error-msg>
  echo "$2" 1>&2
  exit "$1"
}


pkg_version=$(python -m ${PACKAGE} -v 2> /dev/null | cut -d' ' -f2 | sed 's/-.*//')   # sed out  -dev -a -b etc
[[ -n $pkg_version ]] || my_exit 1 "Unable to parse ${PACKAGE} version; check: python -m ${PACKAGE} -v"
echo "$PACKAGE $pkg_version"
asciidoctor -v || my_exit 2 "asciidoctor not found;
please install asciidoctor and rerun.
Here is one way to install asciidoctor:

1. Install rbenv by following instructions at https://github.com/rbenv/rbenv-installer
2. Install ruby and activate an environment
    rbenv install 3.1.2   # the latest stable release when this doc was written
    rbenv global 3.1.2

3. Install Asciidoctor and etensions
    gem install asciidoctor
    gem install rouge "

ver_dir="${DOCS_DIR}/v${pkg_version}"
[[ -d $ver_dir ]] || mkdir -p "$ver_dir"
cmd="asciidoctor -o ${ver_dir}/index.html $DOCS_DIR/index.adoc"
echo "Running:: $cmd"
eval "$cmd" || my_exit 3 "Doc building Failed"

if [[ -f "$DOCS_DIR/index.html" ]]; then
  rm "$DOCS_DIR/index.html"
  ln -s "v$pkg_version/index.html" "$DOCS_DIR/index.html"
fi

[[ -f $DOCS_DIR/versions.adoc ]] &&  asciidoctor -o "$DOCS_DIR/versions.html" "$DOCS_DIR/versions.adoc"
#cp ${ver_dir}/index.html $DOCS_DIR/../$PACKAGE/static/docs.html
