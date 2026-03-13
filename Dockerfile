ARG BUILD_FROM
FROM $BUILD_FROM

ENV LANG C.UTF-8

# Install dependencies
RUN apk add --no-cache \
    python3 \
    py3-pip

# Set working directory
WORKDIR /data

# Copy application files
COPY main.py /
COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
