# MANUAL E2 FIXTURE. Not generated or built by DRAFT.
FROM gcc:13
WORKDIR /workspace
COPY . .
RUN make clean && make
CMD ["make", "test"]
