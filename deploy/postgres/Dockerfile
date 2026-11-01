ARG POSTGRES_MAJOR=16

FROM postgres:${POSTGRES_MAJOR}-bookworm AS zhparser-builder

ARG POSTGRES_MAJOR
ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        automake \
        autoconf \
        build-essential \
        ca-certificates \
        git \
        libtool \
        pkg-config \
        postgresql-server-dev-${POSTGRES_MAJOR} \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --branch 1.2.3 --depth 1 https://github.com/hightman/scws.git /tmp/scws \
    && cd /tmp/scws \
    && touch README \
    && aclocal \
    && autoconf \
    && autoheader \
    && libtoolize \
    && automake --add-missing \
    && ./configure \
    && make -j"$(nproc)" \
    && make install

RUN git clone --branch v2.3 --depth 1 https://github.com/amutu/zhparser.git /tmp/zhparser \
    && make -C /tmp/zhparser -j"$(nproc)" \
    && make -C /tmp/zhparser install

FROM pgvector/pgvector:pg16

ARG POSTGRES_MAJOR

COPY --from=zhparser-builder /usr/lib/postgresql/${POSTGRES_MAJOR}/lib/zhparser.so /usr/lib/postgresql/${POSTGRES_MAJOR}/lib/
COPY --from=zhparser-builder /usr/local/lib/libscws.* /usr/local/lib/
COPY --from=zhparser-builder /usr/share/postgresql/${POSTGRES_MAJOR}/extension/zhparser* /usr/share/postgresql/${POSTGRES_MAJOR}/extension/
COPY --from=zhparser-builder /usr/lib/postgresql/${POSTGRES_MAJOR}/lib/bitcode/zhparser* /usr/lib/postgresql/${POSTGRES_MAJOR}/lib/bitcode/
COPY --from=zhparser-builder /usr/share/postgresql/${POSTGRES_MAJOR}/tsearch_data/*.utf8.* /usr/share/postgresql/${POSTGRES_MAJOR}/tsearch_data/
COPY procurement_dict.txt /usr/share/postgresql/${POSTGRES_MAJOR}/tsearch_data/procurement_dict.txt

RUN ldconfig
