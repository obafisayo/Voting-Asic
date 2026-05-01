module duplicate_checker(
    input [19:0] voter_id_in,
    input check_en, clk, rst_n,
    output reg is_duplicate, check_done
);

    reg voted [0:1048575];

    integer i;
    initial for (i = 0; i < 1048576; i = i + 1) voted[i] = 0;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            is_duplicate <= 0;
            check_done   <= 0;
        end else begin
            check_done <= 0;  // default low

            if (check_en) begin
                if (voted[voter_id_in] == 0) begin
                    voted[voter_id_in] <= 1;
                    is_duplicate <= 0;
                end else begin
                    is_duplicate <= 1;
                end
                check_done <= 1;
            end
        end
    end

endmodule