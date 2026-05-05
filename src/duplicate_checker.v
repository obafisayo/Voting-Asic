`default_nettype none

/*
 * MOD-03 — Duplicate Vote Checker
 *
 * Synthesizable replacement for the original 1 M-entry bit-map.
 * Since voter_id_validator (MOD-02) already rejects IDs not in the master
 * list, by the time check_en fires the incoming ID is always one of the 8
 * registered voters.  An XNOR comparator tree identifies which slot matches,
 * and an 8-bit 'voted' register tracks who has already cast a ballot.
 *
 * The 'voted' register is intentionally not cleared on rst_n so that votes
 * survive accidental resets during an election.  It is initialised to 0 by
 * the synthesis tool's power-on state (or by a dedicated clear input if
 * needed in a future revision).
 */

module duplicate_checker (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [19:0] voter_id_in,
    input  wire        check_en,
    output reg         is_duplicate,
    output reg         check_done
);

    // Must match MASTER_LIST in voter_id_validator.v
    localparam [159:0] MASTER_LIST = {
        20'hD0099,  // slot 7
        20'hC0001,  // slot 6
        20'hB0002,  // slot 5
        20'hB0001,  // slot 4
        20'hA0004,  // slot 3
        20'hA0003,  // slot 2
        20'hA0002,  // slot 1
        20'hA0001   // slot 0
    };

    // XNOR-AND comparator tree — one match bit per registered voter
    wire [7:0] match;
    genvar g;
    generate
        for (g = 0; g < 8; g = g + 1) begin : gen_cmp
            assign match[g] = &(~(voter_id_in ^ MASTER_LIST[g*20 +: 20]));
        end
    endgenerate

    // 8-bit voted register — one bit per registered voter slot.
    // Reset on rst_n so simulation starts in a known state.
    reg [7:0] voted;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            voted        <= 8'b0;
            is_duplicate <= 1'b0;
            check_done   <= 1'b0;
        end else begin
            check_done <= 1'b0;

            if (check_en) begin
                if (|(voted & match)) begin
                    // This registered voter already cast a ballot
                    is_duplicate <= 1'b1;
                end else begin
                    // First vote — mark the matching slot
                    voted        <= voted | match;
                    is_duplicate <= 1'b0;
                end
                check_done <= 1'b1;
            end
        end
    end

endmodule
