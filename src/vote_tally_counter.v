module vote_tally_counter (
    input wire clk,
    input wire rst_n,
    input wire vote_en,
    input wire [2:0] candidate_sel,

    output reg vote_cast,
    output wire [31:0] tally_out
);

// 1. Counter bank (8 candidates, 32-bit each)
reg [31:0] counter [0:7];

// 2. Edge detection for vote_en (rising edge)
reg vote_en_d;
wire vote_event;
assign vote_event = vote_en & ~vote_en_d;

// 3. Sequential logic
integer i;

always @(posedge clk or negedge rst_n)
begin
    if (!rst_n)
    begin
        vote_en_d <= 1'b0;
        vote_cast <= 1'b0;
        for (i = 0; i < 8; i = i + 1)
            counter[i] <= 32'd0;
    end
    else
    begin
        vote_en_d <= vote_en;
        vote_cast <= 1'b0;

        if (vote_event)
        begin
            counter[candidate_sel] <= counter[candidate_sel] + 1;
            vote_cast <= 1'b1;
        end
    end
end

// 4. Read path (combinational)
assign tally_out = counter[candidate_sel];

endmodule
