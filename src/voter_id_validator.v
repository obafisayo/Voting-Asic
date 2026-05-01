/*
 * MOD-02 — Voter ID Validator
 * Checks a 20-bit voter ID against a hard-coded master list using an
 * XNOR-AND comparator tree. Result is available within 2 clock cycles
 * of data_ready assertion.
 */

`default_nettype none

module voter_id_validator #(
    parameter NUM_VOTERS = 8
)(
    input  wire        clk,
    input  wire        rst_n,
    input  wire [19:0] voter_id_in,
    input  wire        data_ready,
    output reg         id_valid,
    output reg         validate_done
);

    // Hard-coded registered voter master list.
    // Packed so the generate loop can extract each 20-bit entry via [g*20 +: 20].
    // voter[0] sits in bits [19:0], voter[7] in bits [159:140].
    localparam [159:0] MASTER_LIST = {
        20'hD0099,  // voter[7]
        20'hC0001,  // voter[6]
        20'hB0002,  // voter[5]
        20'hB0001,  // voter[4]
        20'hA0004,  // voter[3]
        20'hA0003,  // voter[2]
        20'hA0002,  // voter[1]
        20'hA0001   // voter[0]
    };

    // Stage 1: latch voter ID when data_ready fires
    reg [19:0] voter_id_reg;
    reg        stage1_valid;

    // XNOR-AND comparator tree — purely combinational on voter_id_reg.
    // Each bit: XNOR produces 1 where bits match; AND of all 20 produces 1 only
    // on an exact match; OR across all entries detects any match.
    wire [NUM_VOTERS-1:0] match;
    genvar g;
    generate
        for (g = 0; g < NUM_VOTERS; g = g + 1) begin : gen_cmp
            assign match[g] = &(~(voter_id_reg ^ MASTER_LIST[g*20 +: 20]));
        end
    endgenerate

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            voter_id_reg  <= 20'b0;
            stage1_valid  <= 1'b0;
            id_valid      <= 1'b0;
            validate_done <= 1'b0;
        end else begin
            // Cycle 1: register the incoming voter ID
            stage1_valid <= data_ready;
            if (data_ready)
                voter_id_reg <= voter_id_in;

            // Cycle 2: output the comparison result
            validate_done <= stage1_valid;
            if (stage1_valid)
                id_valid <= |match;  // match is combinational on voter_id_reg
        end
    end

endmodule
