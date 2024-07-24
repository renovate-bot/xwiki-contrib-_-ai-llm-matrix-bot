FROM continuumio/miniconda3

WORKDIR /app

COPY environment.yml .
RUN conda env create -f environment.yml

COPY . .

VOLUME /app/nio_store
VOLUME /app/config

# Set the shell to bash
SHELL ["/bin/bash", "-c"]

# Run the command with explicit conda activation
CMD ["bash", "-c", "touch /app/output.log && source activate matrix-bot && (python infinigpt.py > /app/output.log 2>&1 & ) && tail -f /app/output.log"]
