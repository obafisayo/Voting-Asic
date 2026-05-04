module mod05_fsm (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        data_ready,
    input  wire        validate_done,
    input  wire        id_valid,
    input  wire        check_done,
    input  wire        is_duplicate,
    input  wire [2:0]  candidate_in,
    output reg         check_en,
    output reg         vote_en,
    output reg  [2:0]  candidate_sel,
    output reg  [2:0]  status_out
);

    localparam IDLE=3'b000, VALIDATING=3'b001, CHECKING=3'b010, 
               VOTE_CAST=3'b011, DUPLICATE=3'b100, INVALID=3'b101;

    reg [2:0] state, next_state;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) state <= IDLE;
        else        state <= next_state;
    end

    always @(*) begin
        next_state = state;
        case (state)
            IDLE:       if (data_ready) next_state = VALIDATING;
            VALIDATING: if (validate_done) next_state = id_valid ? CHECKING : INVALID;
            CHECKING:   if (check_done)   next_state = is_duplicate ? DUPLICATE : VOTE_CAST;
            VOTE_CAST, DUPLICATE, INVALID: next_state = IDLE;
            default:    next_state = IDLE;
        endcase
    end

    always @(*) begin
        check_en = (state == CHECKING);
        vote_en  = (state == VOTE_CAST);
        candidate_sel = (state == VOTE_CAST) ? candidate_in : 3'b000;
        status_out = state;
    end
endmodule