/*
 * Tiny Tapeout wrapper for MOD-02 — Voter ID Validator
 *
 * Pin protocol (all uio pins configured as inputs, uio_oe = 0):
 *
 *   Step 1 — Load lower byte:
 *     ui_in[7:0]   = voter_id[7:0]
 *     uio_in       = 8'b0000_0101  (byte_write=1, byte_sel=2'b01)
 *
 *   Step 2 — Load upper byte + nibble:
 *     ui_in[7:0]   = voter_id[15:8]
 *     uio_in[7:4]  = voter_id[19:16]
 *     uio_in[3:0]  = 4'b0110        (byte_write=1, byte_sel=2'b10)
 *
 *   Step 3 — Trigger validation:
 *     uio_in       = 8'b0000_1000  (data_ready=1)
 *
 *   After 2 clock cycles:
 *     uo_out[0]    = id_valid      (1 if voter ID is registered)
 *     uo_out[1]    = validate_done (pulses high for one cycle)
 */

`default_nettype none

module tt_um_example (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);

    assign uio_out = 8'b0;
    assign uio_oe  = 8'b0;         // All uio pins are inputs
    assign uo_out[7:2] = 6'b0;

    wire [1:0] byte_sel   = uio_in[1:0];
    wire       byte_write = uio_in[2];
    wire       data_ready = uio_in[3];

    // Accumulate the 20-bit voter ID across two byte-write cycles
    reg [19:0] voter_id_reg;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            voter_id_reg <= 20'b0;
        end else if (byte_write) begin
            case (byte_sel)
                2'b01: voter_id_reg[7:0]   <= ui_in[7:0];
                2'b10: begin
                    voter_id_reg[15:8]  <= ui_in[7:0];
                    voter_id_reg[19:16] <= uio_in[7:4];
                end
                default: ;
            endcase
        end
    end

    wire id_valid;
    wire validate_done;

    voter_id_validator #(.NUM_VOTERS(8)) validator (
        .clk          (clk),
        .rst_n        (rst_n),
        .voter_id_in  (voter_id_reg),
        .data_ready   (data_ready),
        .id_valid     (id_valid),
        .validate_done(validate_done)
    );

    assign uo_out[0] = id_valid;
    assign uo_out[1] = validate_done;

    wire _unused = &{ena, 1'b0};

endmodule
